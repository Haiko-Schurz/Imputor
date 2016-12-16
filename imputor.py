#Imputor

""" Imputor - software for imputing missing mutations in sequencing data by the use
    of phylogenetic trees.
    
    Author - Matthew Jobin
    """


import os
import sys
import random
import glob
import math
import argparse
from argparse import RawTextHelpFormatter
import pickle
import threading
import multiprocessing
import operator
from Bio import AlignIO
from Bio.Phylo.TreeConstruction import *
from Bio import SeqIO
from Bio import Phylo
from Bio.Phylo.Applications import PhymlCommandline
from Bio.Phylo.Applications import RaxmlCommandline
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.Align import MultipleSeqAlignment
import progressbar


class InData(object):
    """Input data from FASTA or VCF file converted internally to sequence data.
        Prepares a dictionary of variants and a list of sequences for processing
        and imputation.
    """
    
    def __init__(self):
        self.ref_seq = None #Reference sequence used to construct sequence data from VCF
        self.sequence = [] #Sequence data
        self.variantset = set() #Set of locations and states of all variants from reference sequence
        self.variants = {} #Dictionary of each sample and its variation from the reference sequence
        self.filebase = None

        # The eight mandatory columns of a VCF file. Here for clarity in functions below.
        self.vcf_chrom = 0
        self.vcf_pos = 1
        self.vcf_id = 2
        self.vcf_ref = 3
        self.vcf_alt = 4
        self.vcf_qual = 5
        self.vcf_filter = 6
        self.vcf_info = 7
        
        return
        
    def load_ref_seq(self, reffile = None):
        """Load a reference sequence for the reconstruction of sequence from
            VCF files.
            
            Keyword arguments:
            reffile -- reference sequence file
            """

        if reffile[-3:] == 'obj':
            refobj = open(reffile, 'rb')
            self.ref_seq = pickle.load(refobj)
        elif reffile[-3:] == 'txt':
            ref_data = open(reffile, 'r')
            self.ref_seq = ref_data.read().rstrip()
        else:
            print "ERROR! Not a known reference sequence type."
        return

    def load_input_data(self, inputfile = None):
        """ Load input data from a file.
            
            Keyword arguments:
            inputfile -- Input data. Accepted formats: FASTA, VCF.
        """
        
        filebase, fileext = os.path.splitext(inputfile)
        self.filebase = filebase
        if inputfile[-5:] == 'fasta':
            self.sequence = AlignIO.read(inputfile, 'fasta')
            self.variants_from_sequence()
        elif inputfile[-3:] == 'vcf':
            self.load_ref_seq(reffile=reffile)
            file_data = open(inputfile, 'r')
            raw_data = []
            for file_line in file_data:
                raw_data.append(file_line.rstrip())
            
            # Split multi-allelic sites
            expanded_file_data = self.vcf_expand_multi_allele(raw_data)

            # Prune non-SNPs
            snps_data = self.vcf_snp_prune(expanded_file_data)
            
            # Generate variants
            for snp_line in snps_data:
                cols = snp_line.split('\t')
                self.variantset.add(cols[self.vcf_pos]+cols[self.vcf_alt])
        
            # Generate sequence from only those areas with any polymorphism
            self.seq_from_variants(raw_data)

        return

    def vcf_expand_multi_allele(self, in_data=None):
        """ Processes multiple ALT alleles in a VCF file. Returns expanded data in list form.
            
            Keyword arguments:
            in_data-- VCF file data.
        """
        expanded_file_data = []
        print "Expanding multi-allele entries..."
        bar = progressbar.ProgressBar(redirect_stdout=True)
        for i in bar(range(len(in_data))):
            file_line = in_data[i]
            cols = file_line.split('\t')

            # If the second character is a (meta-info line) or a blank line, ignore
            if (file_line[:1] == "#") or (cols[self.vcf_chrom] == '\n'):
                continue
            if "," in cols[self.vcf_alt]:
                multi_allele  = cols[self.vcf_alt].split(",")
                for allele in multi_allele:
                    allele_cols = cols
                    # Replace the ALT column with just this allele
                    allele_cols[self.vcf_alt] = allele
                    # Place line with just this allele in the expanded data
                    expanded_file_data.append("\t".join(allele_cols))
            else:
                expanded_file_data.append(file_line)
        return expanded_file_data

    def vcf_snp_prune(self, in_data=None):
        """ Returns a VCF file including only lines containing SNPs.
            
            Keyword arguments:
            in_data-- VCF file data.
        """
        snps_data = []
        print "Pruning non-SNP entries..."
        bar = progressbar.ProgressBar(redirect_stdout=True)
        for i in bar(range(len(in_data))):
            file_line = in_data[i]

            cols = file_line.split('\t')
            # If the second character is a (meta-info line) or a blank line, ignore
            if (file_line[:1] == "#") or (cols[self.vcf_chrom] == '\n'):
                continue
            if len(cols[self.vcf_ref]) > 1 or len(cols[self.vcf_alt]) > 1:  # if not a snp
                continue
            elif cols[self.vcf_ref] == '-' or cols[self.vcf_alt] == '-': # if not a snp
                continue
            elif cols[self.vcf_ref] == '.' or cols[self.vcf_alt] == '.': # if not a snp
                continue
            snps_data.append(file_line)
        return snps_data

    def variants_from_sequence(self):
        """ Returns a list of variants from a reference sequence.
            Intended for use with FASTA input, but will work with any AlignIO object or
            list of sequence data.
        """
        print "Generating variants from sequence..."

        firstseq = self.sequence[0]
        bar = progressbar.ProgressBar(redirect_stdout=True)
        for i in bar(range(len(self.sequence))):
            seq_line = self.sequence[i]
            if len(seq_line) != len(firstseq):
                print "Error! A sequence line is a different size" ,  len(seq_line) , "than the first sequence!" , len(firstseq)
                print seq_line
                return
            diffs = [i for i in xrange(len(firstseq)) if firstseq[i] != seq_line[i]]
            curdiffs = []
            for diff_pos in diffs:
                self.variantset.add(str(diff_pos)+seq_line[diff_pos])
                curdiffs.append(str(diff_pos) + seq_line[diff_pos])
            self.variants[seq_line.name] = curdiffs
        return

    def seq_from_variants(self, raw_data = None):
        """ Generates sequence data from the variants derived from a VCF file.
            Sequence generated includes only polymorphic sites for the sake of brevity.
            
            Keyword arguments:
            raw_data-- VCF file data.
        """
        print "Generating sequence..."
        bar = progressbar.ProgressBar(redirect_stdout=True)
        for i in bar(range(len(raw_data))):
            file_line = raw_data[i]
        # for file_line in raw_data:
            cols = file_line.split('\t')
                
            # Locate header line and read genotype names
            if cols[self.vcf_chrom]=='#CHROM':  # Header line of VCF file
                if cols[self.vcf_info+1]=='FORMAT':  # On header line, a FORMAT column next to the fixed columns?
                    genotype_names = cols[self.vcf_info+2:] # If so, remaining columns are the genotypes
                    genotype_sequence = {}  # Dictionary, thus unique keys
                    ref_seq_list =[] # The reference sequence is converted to a list so individual sites can be altered
                    for ref_seq_char in self.ref_seq:
                        ref_seq_list.append(ref_seq_char)
                else:
                    print "Error. VCF file with no genotype. Cannot create sequence data."
                    return

        # Step through data lines, constructing list of variants. Add an empty list for every genotype.
        for genotype_name in genotype_names:
            self.variants[genotype_name] = []

        # Step through data lines, reconstructing the sequence of each individual
        snps_data = self.vcf_snp_prune(raw_data) #Ensure only SNPs are being processed
        for file_line in snps_data:
            cols = file_line.split('\t')
            if (file_line[:1] == "#") or (cols[self.vcf_chrom] == '\n' or cols[self.vcf_info+1][:2] != "GT"): #If the second character is a (meta-info line) or a blank line or if GT does not start the format line, ignore
                continue
            indiv_genotypes = cols[self.vcf_info+2:] # Assumes all rows same length, as per VCF standard
            for position, indiv_genotype in enumerate(indiv_genotypes): # Iterates through that row of genotypes for this site
                assigned_alleles = indiv_genotype.split("[/|]+") # Split genotype entry on either character phased or unphased
                changed_genotype_names = []
                for allele_pos, assigned_allele in enumerate(assigned_alleles): # Iterates through the alleles
                    changed_genotype_name = genotype_names[position]
                    if len(assigned_alleles)>1: # Only append to genotype name if not haploid
                        changed_genotype_name = changed_genotype_name + str(allele_pos)
                    changed_genotype_names.append(changed_genotype_name)
                for changed_genotype_name in changed_genotype_names:
                    if changed_genotype_name in genotype_sequence:
                        pass
                    else:
                        # genotype_sequence[changed_genotype_name] = [] # Each genotype begins with the reference sequence placed in all valueus
                        genotype_sequence[changed_genotype_name] = ref_seq_list

                            
            
                alt_alleles  = cols[self.vcf_alt].split(",") #List of ALT alleles for this row
                # print alt_alleles
                for allele_pos, assigned_allele in enumerate(assigned_alleles): #Iterates through the alleles
                    if assigned_allele == "0": #Assigned_allele will be 0 for REF and >0 for any ALT
                        # genotype_sequence[changed_genotype_names[allele_pos]].append(cols[self.vcf_ref])
                        pass
                    elif assigned_allele == ".": #VCF format code for missing allele
                        # genotype_sequence[changed_genotype_names[allele_pos]].append("N")
                        genotype_sequence[changed_genotype_names[allele_pos]][int(cols[self.vcf_pos])] = "N"
                    else:
                        # genotype_sequence[changed_genotype_names[allele_pos]].append(alt_alleles[int(assigned_allele)-1])
                        genotype_sequence[changed_genotype_names[allele_pos]][int(cols[self.vcf_pos])] = alt_alleles[int(assigned_allele)-1]
                        if changed_genotype_names[allele_pos] in self.variants: #Keys added to self.variants here
                            self.variants[changed_genotype_names[allele_pos]].append( #to avoid empty entries
                                cols[self.vcf_pos]+alt_alleles[int(assigned_allele) - 1])
                        else:
                            self.variants[changed_genotype_names[allele_pos]] = []
                            self.variants[changed_genotype_names[allele_pos]].append(
                                cols[self.vcf_pos]+alt_alleles[int(assigned_allele) - 1])

        for geno in genotype_sequence.keys():
            genotype_sequence[geno] = ''.join(genotype_sequence[geno])

        # Write to a FASTA file so that it can be read in as SeqIO
        outfile = open('vcf_seq_temp.fasta', 'w')
        lenchk = -1
        for geno in genotype_sequence.keys():
            outfile.write(">")
            outfile.write(geno)
            outfile.write("\n")
            outfile.write(genotype_sequence[geno])
            if (lenchk >= 0 and lenchk != len(genotype_sequence[geno])):
                print "mismatch" + lenchk + " " + len(genotype_sequence[geno])
            outfile.write("\n")
        outfile.close()
        self.sequence = AlignIO.read('vcf_seq_temp.fasta', 'fasta')


class PhyloTree(object):
    """A phylogenetic tree either input from phyloxml format or constructed from sequence
    """

    def __init__(self):
        self.tree = None  # Phylogenetic tree to be loaded or constructed from data. Newick format.
        self.btrees = [] #  Bootstrap replicates of trees. Newick format.
        self.treeparents = {}
        self.btreeparents = []
        self.starttree = None # Phylogenetic tree used as starting tree in RAxML


    def input_tree(self, treetype=None, alpha=None, bootstrap=None, rmodel=None, starttreename=None):
        """ Takes input tree file or sequence data.

            Keyword arguments:
            treetype -- type of tree to be input or constructed
        """

        self.treetype = treetype
        self.starttreename = starttreename

        if self.starttreename:
            if bootstrap > 0:
                print "ERROR: May not provide starting tree with boot != 0."
                sys.exit()
            if self.starttreename[-3:] == 'xml':
                self.starttree = Phylo.read(self.starttreename, "phyloxml")
            elif self.starttreename[-6:] == 'newick':
                self.starttree = Phylo.read(self.starttreename, "newick")


        print "Generating phylogenetic tree..."

        if self.treetype[-3:] == 'xml':
            self.tree = Phylo.read(self.treetype, "phyloxml")
        elif self.treetype == 'pars':
            self.parsimony_tree()
        elif self.treetype == 'RAxML':
            self.raxml_tree(rmodel, bootstrap)
        else:
            self.phyml_tree(alpha, bootstrap)

        self.treeparents = self.all_parents(self.tree)

        for btree in self.btrees:
            self.btreeparents.append(self.all_parents(btree))



    def output_tree(self, inputfile, outtreetype):
        """Outputs tree to file
        """
        filebase, fileext = os.path.splitext(inputfile)
        if outtreetype == 'newick':
            outfile = filebase + "-out.newick"
            Phylo.write(self.tree, outfile, "newick")
        elif outtreetype == 'nexus':
            outfile = filebase + "-out.nexus"
            Phylo.write(self.tree, outfile, "nexus")
        else: # Default Phyloxml
            outfile = filebase + "-out.xml"
            Phylo.write(self.tree, outfile, "phyloxml")

    def all_parents(self, tree):
        parents = {}
        for clade in tree.find_clades():
            for child in clade:
                parents[child] = clade
        return parents

    def collect_kids(self, clade, kids, depth, maxdepth):
        """ Recursive function for collecting all children to specified depth

            Keyword arguments:
            clade -- current node of tree
            kids --list of all collected children
            depth -- current depth of search
            maxdepth -- maximum depth of search
        """
        #
        if depth < maxdepth:
            for child in clade:
                if child.name:
                    kids.append(child)
                self.collect_kids(child, kids, depth+1, maxdepth)
        return kids

    def collect_all_kids(self, clade, kids):
        """ Recursive function for collecting all children of clade

            Keyword arguments:
            clade -- current node of tree
            kids -- lost of all collected children
        """
        for child in clade:
            if child.name:
                kids.append(child)
            self.collect_all_kids(child, kids)
        return kids

    def get_siblings(self, clade):
        siblings = []
        if clade in phytree.treeparents:  # Will not go past the root clade
            for kid in phytree.treeparents[clade]:
                if kid == clade:
                    pass
                else:
                    siblings.append(kid)
        return siblings

    def collect_kids_rootward(self, clade):
        kids = []
        for child in clade:
            if child.name:
                kids.append(child)

    def parsimony_tree(self):
        """ Constructs a tree via maximum parsimony using Biopython's ParsimonyTreeConstructor.

        """
        print "Generating maximum parsimony tree.."
        scorer = ParsimonyScorer()
        searcher = NNITreeSearcher(scorer)
        constructor = ParsimonyTreeConstructor(searcher)
        self.tree = constructor.build_tree(indata.sequence)

    def raxml_tree(self, rmodel=None, bootstrap=None):
        """ Constructs a tree via maximum likelihood by invoking external software RAxML.
            See docs for RAxML installation and setup.

            Keyword arguments:
            rmodel -- model type for input into RAxML.

        """
        cpus = multiprocessing.cpu_count()
        print "Invoking RAxML on " , cpus, "threads"
        # Erase RaXML intermediate files from previous runs
        raxml_glob = glob.glob('RAxML_*')
        for delfile in raxml_glob:
            os.remove(delfile)

        # Output sequence to a temp FASTA file
        tempfastafile = indata.filebase + "_fastatmp.fasta"
        AlignIO.write(indata.sequence, tempfastafile, "fasta")
        rng = random.SystemRandom()  # Uses /dev/urandom


        raxml_args = {}
        raxml_args["sequences"] = tempfastafile
        raxml_args["model"] = rmodel
        raxml_args["name"] = "imputor"
        raxml_args["parsimony_seed"] = rng.randint(0, sys.maxint)
        raxml_args["threads"] = cpus



        if self.starttree:
            print "writing start tree"
            Phylo.write(self.starttree, "RAxML_imputorstartingtree.newick", "newick")
            raxml_args["starting_tree"] = "RAxML_imputorstartingtree.newick"
        elif bs > 0:
            raxml_args["num_replicates"] = bootstrap
            raxml_args["algorithm"] = "a"
            raxml_args['rapid_bootstrap_seed'] = rng.randint(0, sys.maxint)


        raxml_cline = RaxmlCommandline(**raxml_args)

        out_log, err_log = raxml_cline()
        if verbose:
            print err_log
            print out_log
        self.tree = Phylo.read("RAxML_bestTree.imputor", "newick")
        if bootstrap>0:
            self.btrees = list(Phylo.parse("RAxML_bootstrap.imputor", "newick"))

        # Erase RaXML intermediate files
        if not verbose:
            raxml_glob = glob.glob('RAxML_*')
            for delfile in raxml_glob:
                os.remove(delfile)

    def phyml_tree(self, alpha=None, boostrap=None):
        """ Constructs a tree via maximum likelihood by invoking external software PhyML.
            See docs for PhyML installation and setup.

        """
        print "Invoking PhyML..."
        # Output sequence to a temp FASTA file
        tempfastafile = indata.filebase + "_fastatmp.fasta"
        AlignIO.write(indata.sequence, tempfastafile, "fasta")
        tempphyfile = indata.filebase + "_phytmp.phy"
        AlignIO.convert(tempfastafile, "fasta", tempphyfile, "phylip-relaxed")

        phyml_args = {}
        phyml_args["input"] = tempphyfile
        phyml_args["alpha"] = "e"
        if self.starttree:
            Phylo.write(self.starttree, "PhyML_imputorstartingtree.newick", "newick")
            phyml_args["input_tree"] = "PhyML_imputorstartingtree.newick"
        elif bootstrap > 0:
            phyml_args["bootstrap"] = bootstrap

        cmdline = PhymlCommandline(**phyml_args)
        print "Commandline for PhyML: " + str(cmdline)
        out_log, err_log = cmdline()
        if verbose:
            print err_log
            print out_log
        phytreefile = tempphyfile + "_phyml_tree.txt"
        self.tree = Phylo.read(phytreefile, "newick")
        if bootstrap > 0:
            phybtreefile = tempphyfile + "_phyml_boot_trees.txt"
            self.btrees = Phylo.parse(phybtreefile, "newick")


class Imputation(object):
    """Imputation of missing mutations given input data and a phylogenetic tree.
    """

    def __init__(self, indata, phytree, mutrate, threshold, tstv, multi, bmchk, brchk):
        self.cpucount = multiprocessing.cpu_count()
        self.workseq = {}
        self.imputedseq = MultipleSeqAlignment([])
        self.indata = indata
        self.phytree = phytree
        self.mu = mutrate
        self.threshold = threshold
        self.tstv = tstv
        self.imputelist = []
        self.bootreps = {}
        self.multi = multi
        self.bmchk = bmchk
        self.acgt = set(['A', 'C', 'G', 'T'])
        self.missing = set(['.', '-', 'N'])
        self.brchk = brchk

        for seq in indata.sequence:
            self.workseq[seq.name] = list(str(seq.seq))  # Begin with output sequence matching input


    def impute(self, imputetype, depth, neighbors, bootstrap):
        """ Sets up multiprocessing of imputation function for all terminal nodes.

            Keyword arguments:
            imputetype -- Type of search used to locate possible sites to impute.
            depth -- Depth of search up and down tree to find neighbours.
            neighbors -- Minimum number of identical non-missing neighbors in order to impute.
            bootstrap -- Number of bootstrap replicates.

        """

        impute_threads =[]

        if bootstrap > 0: # Bootstrap replicates
            self.brchk = False # No need to check branch lengths when comparing bootstrap
            bpar = iter(phytree.btreeparents)
            for btree in self.phytree.btrees:
                terms = btree.get_terminals()
                random.shuffle(terms)
                bparents = next(bpar)
                for term in terms:
                    t = threading.Thread(target=self.impute_bootstrap, args=(term, btree, bparents, neighbors))
                    t.start()
                    impute_threads.append(t)
                for thread in impute_threads:  # Block until all complete
                    thread.join()


            for bootrep in self.bootreps:
                if(self.bootreps[bootrep][0]/self.bootreps[bootrep][1] > (1-self.threshold)):
                    newimpute = bootrep.split("-")
                    newimpute.append(str(self.bootreps[bootrep][0]/self.bootreps[bootrep][1]))
                    self.imputelist.append(newimpute)
                    self.workseq[newimpute[0]][int(newimpute[1][:-1])] = newimpute[3]


        else:
            Phylo.draw_ascii(self.phytree.tree)
            terms = self.phytree.tree.get_terminals()  # Get all internal nodes on tree. These are the ones with samples.
            random.shuffle(terms)
            for term in terms:
                t = threading.Thread(target=self.impute_threshold, args=(term, self.phytree.tree, self.phytree.treeparents, neighbors))
                t.start()
                impute_threads.append(t)
            for thread in impute_threads:  # Block until all complete
                thread.join()
            for newimpute in self.imputelist:
                if float(newimpute[4]) < self.threshold:
                    self.workseq[newimpute[0]][int(newimpute[1][:-1])] = newimpute[3]

        self.process_imputed()


    def impute_bootstrap(self, term, btree, bparents, neighbors):
        """ Imputation with bootstrap replicates.

            Keyword arguments:
            term -- Terminal node on tree to be examined.
            btree -- Tree to be examined.
            bparents - List of parent nodes of each node in tree.
            neighbors -- Minimum number of identical neighbors to impute.

        """
        for curvar in self.indata.variantset:
            newimpute = self.detect_by_parsimony(term, btree, curvar,
                                                 bparents, neighbors)

            bootfront = "-".join(newimpute[0:4])
            if bootfront not in self.bootreps:
                self.bootreps[bootfront] = [0,0]
            if newimpute[4] == "1":
                self.bootreps[bootfront][0] = self.bootreps[bootfront][0] + 1
            self.bootreps[bootfront][1] = self.bootreps[bootfront][1] + 1

    def impute_threshold(self, term, tree, parents, neighbors):
        """ Imputation via branch length.

            Keyword arguments:
            term -- Terminal node on tree to be examined.
            tree -- Tree to be examined.
            parents - List of parent nodes of each node in tree.
            nc -- Minimum number of identical neighbors to impute.

        """
        for curvar in self.indata.variantset:
            newimpute = self.detect_by_parsimony(term, tree, curvar, parents, neighbors)
            self.imputelist.append(newimpute)


    def impute_missing(self, term, depth):
        """Imputes missing mutations.

            Keyword arguments:
            term -- Terminal node to be compared to neighbours.
            depth -- Depth of search up and down tree to find neighbours.
        """

        theparent = None
        curnode = term
        for x in range(0, depth):  #Descend tree to user-specified depth
            if curnode in phytree.treeparents:  #Will not go past the root clade
                partemp = theparent
                theparent = phytree.treeparents[curnode]  #Should be an internal clade with no associated sample
                curnode = partemp
        if theparent:  # If we have found a valid parent clade at specififed depth
            empty = []
            allkids = phytree.collect_kids(theparent, empty, 0, depth)
            neighbour_variantset = set()  # Set of all variants for this particular group of neighbours
            for kid in allkids:
                thesevars = indata.variants[str(kid)]  # Extract all the variants
                for thisvar in thesevars:
                    neighbour_variantset.add(thisvar)
            for curvar in neighbour_variantset:
                orig = curvar[-1:]
                present = 0
                curpresent = False
                for kid in allkids:
                    thesevars = indata.variants[str(kid)]  # extract all the variants
                    if curvar in thesevars:
                        present = present + 1
                        if term == kid:
                            curpresent = True
                if curpresent: #Current
                    pass
                else:
                   if len(allkids) > 2 and float(present) / float(len(allkids)) > 0.5:
                        self.workseq[str(term)][int(curvar[:-1])] = curvar[-1:]

    def impute_by_reference(self, term):
        """Imputes missing mutations.

            Keyword arguments:
            term -- Terminal node to be compared to neighbours.

        """
        # print "\n******\n For term: " + str(term)
        for curvar in self.indata.variantset:  # ALL variants in sample
            origseq = self.workseq[str(term)][int(curvar[:-1])]
            # print "\nFor variant: " + str(curvar) + " : " + origseq
            nearest = set()
            curnode = term
            while len(nearest) < 2:
                if curnode in phytree.treeparents:  # Will not go past the root clade, which has no parent
                    theparent = phytree.treeparents[curnode]  # Should be an internal clade with no associated sample
                    empty = []
                    # print "curnode: " + str(curnode) + " parent: " + str(theparent)
                    allkids = phytree.collect_kids(theparent, empty, 0, depth)
                    for kid in allkids:
                        if kid != term:
                            nearest.add(kid)
                else:
                    break
                curnode = theparent

            nearseq = []

            for kid in nearest:
                # print kid
                kidseq = self.workseq[str(kid)][int(curvar[:-1])]
                nearseq.append(kidseq)

            # print "target: " + origseq + " neighbors: " + str(nearseq)
            if (origseq == "N" or origseq == "." or origseq == "-") and len(nearseq) >= 2:
                if (nearseq[0] == nearseq[1]):
                    # print "\n******IMPUTE? For term: " + str(term) + " For variant: " + str(curvar) + " : " + origseq
                    # print "orig:" + str(origseq) + " ref: " + refseq + " nearseq: " + str(nearseq)
                    self.workseq[str(term)][int(curvar[:-1])] = nearseq[0]
            elif (origseq == "A" or origseq == "C" or origseq == "G" or origseq == "T") and len(nearseq) >= 2:
                refseq = indata.ref_seq[int(curvar[:-1])]
                # print "IMPUTE? orig:" + str(origseq) + " ref: " + refseq + " nearseq: " + str(nearseq)
                if (nearseq[0] == nearseq[1]) and (origseq != nearseq[0]) and (origseq == refseq):
                    self.workseq[str(term)][int(curvar[:-1])] = nearseq[0]
                    # print "IMPUTE? orig:" + str(origseq) + " ref: " + refseq + " nearseq: " + str(nearseq)

    def impute_by_parsimony(self, term, terms):
        # print "\n*****" + str(term)
        dists = {}
        for other in terms:
            if term != other:
                path = self.tree.tree.trace(term, other)
                dists[other] = len(path)
                # print str(path) + " : " + str(len(path))
        sorted_dists = sorted(dists.items(), key=operator.itemgetter(1)) #Tuple sorted by value

        # for sorted_other in sorted_dists:
        #     print str(sorted_other[0]) + ": " + str(sorted_other[1])

        for curvar in self.indata.variantset: #ALL variants in sample
            # print "For variant: " + str(curvar)
            origseq = self.workseq[str(term)][int(curvar[:-1])]
            nearest = []
            for sorted_other in sorted_dists:
                sortseq = self.workseq[str(sorted_other[0])][int(curvar[:-1])]
                if sortseq == "A" or sortseq == "C" or sortseq == "G" or sortseq == "T":
                    nearest.append(sortseq)

            if (origseq == "N" or origseq == "." or origseq == "-") and len(nearest) > 1:
               if (nearest[0] == nearest[1]) and origseq != nearest[0]:
                   #print str(curvar)  + " missing? would change to a " + nearest[0]
                   self.workseq[str(term)][int(curvar[:-1])] = nearest[0]
            elif (sortseq == "A" or sortseq == "C" or sortseq == "G" or sortseq == "T") and len(nearest) > 2:
                if (nearest[0] == nearest[1]) and (nearest[0] == nearest[2]) and origseq != nearest[0]:
                    for outgrp in xrange(2, len(nearest)):
                        if nearest[outgrp] == origseq:
                            # print str(term) + " Reversion? " + str(curvar) + " " + str(origseq) + ": " +str(nearest)
                            theparent = self.tree.treeparents[term]
                            tstv = self.transversionchk(nearest[0], self.workseq[str(term)][int(curvar[:-1])],  self.tstv)
                            if tstv > 0:
                                btime = self.tree.tree.distance(theparent, term)
                                pk = (((self.mu * btime) ** 1) * (math.exp(-self.mu * btime)))/ math.factorial(1) * tstv
                                # print "length of term branch " + str(self.tree.tree.distance(theparent, term)) + " time " + str(self.tree.tree.distance(theparent, term) / self.mu) + " tstv " + str(tstv) + " chance: " + str(pk)
                                if pk < self.threshold:
                                    self.workseq[str(term)][int(curvar[:-1])] = nearest[0]

    def process_imputed(self):
        for key, value in self.workseq.iteritems():
            seqrec = SeqRecord(Seq("".join(value)), id=key, name=key)
            self.imputedseq.append(seqrec)
        self.imputedseq.sort()

    def transversionchk(self, a, b, tstv):
        # print "from " + str(a) + " to " + str(b)
        if a == "A":
            if b == "G":
                return tstv
        if a == "G":
            if b == "A":
                return tstv
        if a == "C":
            if b == "T":
                return tstv
        if a == "T":
            if b == "C":
                return tstv
        if a in ("A", "C", "G", "T") and b in ("A", "C", "G", "T"):
            return 1/tstv
        return -1

    def backmutchk(self, curparent, allneighbours, curvar, origseq):
        backmut = False
        while curparent in phytree.treeparents:  # Search for allele farther away
            if backmut == True:
                return True
            nextparent = phytree.treeparents[curparent]
            empty = []
            allkids = phytree.collect_kids(curparent, empty, 0, depth)
            for kid in allkids:
                kidseq = self.workseq[str(kid)][int(curvar[:-1])]
                if kid not in allneighbours and kidseq == origseq:
                    backmut = True
                allneighbours.add(kid)
            curparent = nextparent
        return False

    def detect_by_parsimony(self, term, tree, curvar, parents, nc):
        neighbors = set()
        curnode = term

        #Collect closest neighbors on tree
        while len(neighbors) < nc:
            if curnode not in parents: # will not go past the root
                # print "not in parents"
                break
            curparent = parents[curnode]
            # print "\t", curparent
            empty = []
            allkids = phytree.collect_all_kids(curparent, empty)
            for kid in allkids:
                if kid is not term:
                    # print "\t\t", kid
                    neighbors.add(kid)
                    if len(neighbors) >= nc:
                        break
            curnode = curparent
        nearest = set()
        orig = self.workseq[str(term)][int(curvar[:-1])]
        for neighbor in neighbors:
            nearest.add(self.workseq[str(neighbor)][int(curvar[:-1])])

        only = nearest.pop() # Will now be a single base
        if only in self.missing:
            return [str(term), curvar, orig, only, "0"]
        if len(nearest) != 1: # The nearest do not all match
            return [str(term), curvar, orig, only, "0"]
        if orig != only: # If target sequence does not match matching non-missing neighbors
            if self.bmchk:
                if self.backmutchk(curparent, neighbors, curvar, orig) == False:
                    return [str(term), curvar, orig, only, "0"]
            if self.brchk == True:
                tstv = self.transversionchk(only, self.workseq[str(term)][int(curvar[:-1])], self.tstv)
                if tstv > 0:
                    btime = tree.distance(parents[term], term)
                    pk = (((self.mu * btime) ** 1) * (math.exp(-self.mu * btime))) / math.factorial(1) * tstv
                    if pk < self.threshold:
                        return [str(term), curvar, orig, only, str(pk)]
                    else:
                        return [str(term), curvar, orig, only, "0"]
                else:
                    return [str(term), curvar, orig, only, "0"]
            else:
                return [str(term), curvar, orig, only, "1"]
        else:
            return [str(term), curvar, orig, only, "0"]


    def output_imputed(self, inputfile, out, impout):
        if verbose:
            if len(self.imputelist) > 0:
                print "Imputed Mutations"
                print "ID | VAR | FROM | TO | LIKELIHOOD"
                for imputed in self.imputelist:
                    print " | ".join(imputed)
                print "\n"
            print impute.imputedseq

        filebase, fileext = os.path.splitext(inputfile)
        if impout == True:
            impoutfilename = filebase + "-impout.csv"
            impoutfile = open(impoutfilename, 'w')
            impoutfile.write("Imputed Mutations")
            impoutfile.write("ID, VAR, FROM, TO, LIKELIHOOD\n")
            for imputed in impute.imputelist:
                impoutfile.write(",".join(imputed))
                impoutfile.write("\n")
        if out == "vcf":
            print "VCF output not yet implemented."
            return
        else: # default to fasta
            outseqfile = filebase + "-seqout.fasta"
            outfile = open(outseqfile, 'w')
            outseq = {}
            for seq in self.imputedseq:
                outseq[seq.id] = str(seq.seq)
            for x in sorted(outseq.keys()):
                outfile.write(">")
                outfile.write(str(x))
                outfile.write("\n")
                outfile.write(outseq[x])
                outfile.write("\n")


            # SeqIO.write(self.imputedseq, outseqfile, "fasta")


class ChromStats(object):
    """Data from object or text files for assessment of false negative rates.
    """

    def __init__(self, indata, haplogroupfile, weightsfile, polysfile):
        self.haplogroups = {}  # Trusted haplogroups
        self.weights = {}
        self.polys = {}

        if haplogroupfile[-3:] == 'obj': #object file
            haplogroupobj = open(haplogroupfile, 'rb')
            self.haplogroups = pickle.load(haplogroupobj)
        elif haplogroupfile[-3:] == 'txt': #text file
            file_data = open(haplogroupfile, 'r')
            raw_data = []
            for file_line in file_data:
                raw_data.append(file_line.rstrip())

        if weightsfile[-3:] == 'obj': #object file
            weightsobj = open(weightsfile, 'rb')
            self.weights = pickle.load(weightsobj)
        elif weightsfile[-3:] == 'txt': #text file
            file_data = open(weightstfilefile, 'r')
            raw_data = []
            for file_line in file_data:
                raw_data.append(file_line.rstrip())

        if polysfile[-3:] == 'obj': #object file
            polysobj = open(polysfile, 'rb')
            self.polys = pickle.load(polysobj)
        elif polysfile[-3:] == 'txt': #text file
            file_data = open(polysfile, 'r')
            raw_data = []
            for file_line in file_data:
                raw_data.append(file_line.rstrip())





if __name__ == "__main__":
    print "\n\n***IMPUTOR ***\n\n"
    
    parser = argparse.ArgumentParser(description="IMPUTOR is a program for the phylogeny-aware imputation of: \n\n\t"\
                                     "mutations.\n\t"\
                                     "- ",formatter_class=RawTextHelpFormatter)
        
    parser.add_argument('-file',metavar='<file>',help='input file: .fasta, .vcf or .var', required=True)
    parser.add_argument('-ref',metavar='<ref>',help='reference sequence, .txt or .obj')
    parser.add_argument('-tree',metavar='<tree>',help='tree type; <treefilename.xml>, pars, RAxML, PhyML', default='RAxML')
    parser.add_argument('-outtree', metavar='<outtree>', help='Output format for tree', default='phyloxml')
    parser.add_argument('-alpha',metavar='<alpha>',help='Value of gamma shape parameter.', default='e')
    parser.add_argument('-boot',metavar='<boot>',help='Number of bootstrap replicates.', default='10')
    parser.add_argument('-rmodel',metavar='<rmodel>',help='Model type for RaXML.', default='GTRCAT')
    parser.add_argument('-depth', metavar='<depth>', help='Depth of search toward root for collecting neeighbors.', default=2)
    parser.add_argument('-hapobj', metavar='<hapobj>', help='Haplogroups file.')
    parser.add_argument('-wtobj', metavar='<wtobj>', help='Weights file.')
    parser.add_argument('-polyobj', metavar='<polyobj>', help='Polymorphisms file.')
    parser.add_argument('-impute', metavar='<impute>',help='Imputation.', default='pars')
    parser.add_argument('-mutrate', metavar='<mutrate>', help='Mutation rate.', default='8.71e-10')
    parser.add_argument('-threshold', metavar='<threshold>', help='Acceptance threhsold for imputation.',
                    default='0.05')
    parser.add_argument('-tstv', metavar='<tstv>', help='Transition/travsersion ratio.', default='2.0')
    parser.add_argument('-out', metavar='<out>', help='Output file type: fasta or vcf', default='fasta')
    parser.add_argument('-impout', metavar='<impout>', help='Output list of imputed mutations', default=True)
    parser.add_argument('-multi', metavar='<multi>', help='Multiprocessing.', default=True)
    parser.add_argument('-backmutchk', metavar='<backmutchk>', help='Only impute non-missing sites if it is a suspected back-mutation.', default=True)
    parser.add_argument('-neighbors', metavar='<neighbors>', help='Number of neighbors that must be identical in order to impute.',
                        default=3)
    parser.add_argument('-branchchk', metavar='<branchchk>',
                        help='<>.', default=True)
    parser.add_argument('-starttree', metavar='<starttree>', help='Newick or phyloxml starting tree for RAxML')
    parser.add_argument('-verbose', metavar='<verbose>', help='Verbose output.', default=True)


    args = parser.parse_args()
    inputfile = args.file
    reffile = args.ref
    treetype = args.tree
    outtreetype = args.outtree
    alpha = args.alpha
    bootstrap = int(args.boot)
    rmodel = args.rmodel
    hapobj = args.hapobj
    wtobj = args.wtobj
    polyobj = args.polyobj
    depth = int(args.depth)
    imputetype = args.impute
    mutrate = float(args.mutrate)
    threshold = float(args.threshold)
    tstv = float(args.tstv)
    outtype = args.out
    impout = args.impout
    multi = args.multi
    backmutchk = args.backmutchk
    neighbors = int(args.neighbors)
    branchchk = args.branchchk
    starttree = args.starttree
    verbose = args.verbose

    sys.setrecursionlimit(10000)

    print "Working in" + os.getcwd() + " on " + inputfile +  " using " + treetype

    indata = InData()


    indata.load_input_data(inputfile = inputfile)
    print "\n****************\nVARIANTS\n****************\n\n"
    for i in indata.variants.keys():
        print i + ": " + str(indata.variants[i])

    print "\n****************\nSEQUENCE\n****************\n\n"
    print indata.sequence

    print "\n****************\nTREE\n****************\n\n"
    phytree = PhyloTree()
    phytree.input_tree(treetype = treetype, alpha = alpha, bootstrap = bootstrap, rmodel = rmodel, starttreename = starttree)
    Phylo.draw_ascii(phytree.tree)
    phytree.output_tree(inputfile, outtreetype)


    print "\n****************\nIMPUTATION\n****************\n\n"
    impute = Imputation(indata, phytree, mutrate, threshold, tstv, multi, backmutchk, branchchk)
    impute.impute(imputetype, depth, neighbors, bootstrap)
    impute.output_imputed(inputfile, outtype, impout)




    # print "\n****************\nFALSE NEGATIVES\n****************\n\n"
    # stats = ChromStats(indata, hapobj, wtobj, polyobj)
    # #print stats.haplogroups
    # #print stats.weights
    # #print stats.polys



else:
    print("IMPUTOR is being imported into another module. Not yet implemented.")
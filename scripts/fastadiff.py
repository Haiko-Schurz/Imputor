# Fastadiff

""" Fastadiff

    Author - Matthew Jobin
    """

import argparse
from argparse import RawTextHelpFormatter
import os

parser = argparse.ArgumentParser(description="This script compares \n\n\t" \
                                             "- two FASTA files.\n\t" \
                                             "- ",formatter_class=RawTextHelpFormatter)


parser.add_argument('-afile',metavar='<afile>',help='input file A: .fasta', required=True)
parser.add_argument('-bfile',metavar='<bfile>',help='input file B: .fasta')
parser.add_argument('-impoutfile',metavar='<impoutfile>',help='impout file')
parser.add_argument('-silent', dest='silent', help='None of your beeswax.',
					action='store_true')
parser.set_defaults(silent=False)

args = parser.parse_args()
afile = args.afile
bfile = args.bfile
impoutfile = args.impoutfile
silent = bool(args.silent)

if not silent:
	print "\n\n***FASTADIFF ***\n\n"

twofile = True

if afile[-5:] != 'fasta':
    print "Error: FASTA files with a .fasta extension only."
    quit()

abasename = os.path.basename(afile)
afilebase, afileext = os.path.splitext(abasename)
    
aseq = {}
afile_data = open(afile, 'r')
for file_line in afile_data:
    if file_line[:1] is '>':
        id = file_line[1:].rstrip()
        data_line = next(afile_data).rstrip()
        aseq[id] = data_line

if not silent:
	print "Number of read sequences in file" , " " ,len(aseq)

imputedic = {}

if impoutfile:
	impoutfile_data = open(impoutfile, 'r')
	for ifile_line in impoutfile_data:
		impline = ifile_line.rstrip()
		impcols = impline.split('\t')
		impname = impcols[0] + "-" + impcols[1]
		imputedic[impname] = ifile_line
		

outfilebase, outfileext = os.path.splitext(afile)
outfilename =  outfilebase + "-pairwise.txt"
outfile = open(outfilename, 'w')

batchlist = []

if not bfile:
	print "not bfile"
	twofile = False
	bfile = afile
	batchlist.append(afile)
elif os.path.isdir(bfile):
	for bbfile in os.listdir(bfile):
		if bbfile.endswith(".fasta"):
			batchlist.append(bfile + "/" + bbfile)
elif os.path.isfile(bfile):
	if bfile.endswith(".fasta"):
		batchlist.append(bfile)
	else:
		print "Input file must be either .fasta or .vcf"
		exit()
else:
	print "Input file must be either .fasta or .vcf"
	exit()

pairwises = []

for bfile in batchlist:

# 	mmimpouts = []
	bbasename = os.path.basename(bfile)
	bfilebase, bfileext = os.path.splitext(bbasename)
	
	bseq = {}
	bfile_data = open(bfile, 'r')
	for file_line in bfile_data:
		if file_line[:1] is '>':
			id = file_line[1:].rstrip()
			data_line = next(bfile_data).rstrip()
			bseq[id] = data_line
	if not silent:
		print "Number of read sequences in file" , " " ,len(bseq)


	totdiffs = 0
	totmissdiffs = 0
	totbases = 0
	seqdiffs = {}
	diffsites = {}

	if twofile:
	#Comparison
		for k in aseq:
			if k in bseq:
				xaseq = aseq[k]
				xbseq = bseq[k]
				if len(xaseq) != len(xbseq):
					print "Error: lines should be same size for sequences: ", k , " Skipping."
					continue
				diffs = [i for i in xrange(len(xaseq)) if xaseq[i] != xbseq[i]]
				totdiffs += len(diffs)
				totbases += len(xaseq)
				seqdiffs[k] = (float(len(diffs)) / float(len(xaseq)))
				diffsites[k] = diffs
	else:
		for k in aseq:
			for l in bseq:
				if k == l:
					continue
				xaseq = aseq[k]
				xbseq = bseq[l]
				if len(xaseq) != len(xbseq):
					print "Error: lines should be same size for sequences: ", k , " Skipping."
					continue
				diffs = [i for i in xrange(len(xaseq)) if xaseq[i] != xbseq[i]]
				totdiffs += len(diffs)
				totbases += len(xaseq)
				seqdiffs[k] = (float(len(diffs)) / float(len(xaseq)))
				print k + "\t" + l + "\t" + str((float(len(diffs)) / float(len(xaseq))))
				diffsites[k] = diffs

			
	if not silent:
		print "\n********* " , bfile		
		print "ID\tDiffs"
	for x in sorted(diffsites.keys()):
		for tdiff in diffsites[x]:
			diffname = x + "-" + str(tdiff)
# 			if impoutfile:
# 				mmimpouts.append(imputedic[diffname])
		if len(diffsites[x]) > 0:
			if not silent:
				print x, "\t", diffsites[x]
	if not silent:
		print "Differences: ", totdiffs, " out of " , totbases
	pairwise = float(totdiffs) / float(totbases)
	if not silent:
		print "Pairwise Distance: " , pairwise
	outfile.write(str(pairwise))
	pairwises.append(pairwise)
	outfile.write("\n")
# 	impoutoutname = afilebase + "-" +  bfilebase + "-mmimpout.txt"
# 	impoutoutfile = open(impoutoutname, 'w')
# 	impoutoutfile.write("SUBJECTID\t VAR\t FROM\t TO\t TYPE\tPASS\tIMPUTED\n")
# 	for imputed in mmimpouts:
# 		impoutoutfile.write(imputed)
# 		impoutoutfile.write("\n")
# 	impoutoutfile.close()

if not silent:
	print "Average Pairwise Distance for all infiles: "
print sum(pairwises) / float(len(pairwises))











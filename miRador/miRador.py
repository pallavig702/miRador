#!/usr/local/bin/python3.3

# miRunner is the miRNA prediction script within the miRador package.
# It functions by first identifying inverted repeats within the genome.
# Then, it maps all small RNAs to the identified inverted repeats to create
# a list of candidate miRNAs.

#### Written by Reza Hammond
#### rkweku@udel.edu 

### miRNA identification criteria: https://doi.org/10.1105/tpc.17.00851

######## IMPORT ################
import configparser
import datetime
import os
import multiprocessing
import time
import shutil
import sys

from itertools import repeat

import annotateCandidates
import filterPrecursors
import genome
import library
import mapSRNAsToIRs

def miRador():
    """Parse configuration file and make necessary calls to the various
    helper functions to perform the entire miRNA prediction of the user
    provided input files. This function primarily serves as a wrapper
    to those other functions in other files

    """

    progStart = time.time()

    ######################## Parse Config File ###############################
    configFilename = sys.argv[1]
    config = configparser.ConfigParser()
    config.read(configFilename)

    # Get the preprocessing arguments
    #runPreprocessFlag = config.get("Preprocess", "runPreprocessFlag")

    # Get the genome file name
    genomeFilename = config.get("Genome", "genomeFilename")

    # Get the EInverted arguments
    runEInvertedFlag = int(config.get("EInverted", "runEInvertedFlag",
        fallback = 1))
    match = int(config.get("EInverted", "match", fallback = 3))
    mismatch = int(config.get("EInverted", "mismatch", fallback = 4))
    gap = int(config.get("EInverted", "gap", fallback = 6))
    threshold = int(config.get("EInverted", "threshold", fallback = 40))
    maxRepLen = int(config.get("EInverted", "maxRepLen", fallback = 300))

    # Get the Libraries arguments and parse the libraries into a list
    # of strings. User can input a list of files or just a directory
    # holding all of the tag count files
    libFilenamesList = []
    libFilenamesString = config.get("Libraries", "libFilenamesList",
        fallback = "")
    libFolder = config.get("Libraries", "libFolder", fallback = "")

    # If individual libraries were given, split the string on commas and
    # store them in libFilenamesList 
    if(libFilenamesString):
        libFilenamesList = libFilenamesString.split(",")

    # If libFolder was specified, loop through the files in the folder
    # and add all files that end with "chopped.txt" to to libFilenamesList
    if(libFolder):
        for file in os.listdir(libFolder):
            if file.endswith("chopped.txt"):
                libFilenamesList.append("%s/%s" % (libFolder,
                    os.path.join(file)))

    # Grab the information for the BLAST variables
    subjectSequencesFilename = config.get("BLAST", "subjectSequencesFilename")
    dbFilename = config.get("BLAST", "dbFilename")
    organism = config.get("BLAST", "organism")

    parallel = int(config.get("General", "parallel"))
    nthreads = config.get("General", "nthreads")
    bowtiePath = os.path.expanduser(config.get("General", "bowtiePath"))
    bowtieBuildPath = os.path.expanduser(config.get("General",
        "bowtieBuildPath"))
    einvertedPath = os.path.expanduser(config.get("General", "einvertedPath"))
    perlPath = os.path.expanduser(config.get("General", "perlPath"))
    outputFolder = config.get("General", "outputFolder", fallback = "")

    # Required overhang between top and bottom strands of miRNA duplex
    # Hardcoded to 2 here, but in such a way that could technically allow
    # modifications
    overhang = 2

    ###########################################################################

    ### Check the existence of all input files and that the paths to 
    # external functions exist before running

    # Make sure the genome file exists as defined
    if(not os.path.isfile(genomeFilename)):
        print("%s could not be found! Please check that the file path "\
            "was input correctly" % genomeFilename)
        sys.exit()

    # Do not allow execution if both libFilenamesString and libFolder
    # are defined to anything other than empty strings
    if(libFilenamesString and libFolder):
        print("You specified both libName and libNamesList, but only one"\
            "can exist. Delete one and try running again")
        sys.exit()

    # Loop through all libraries in libFilenamesList and confirm that they
    # exist before running
    for libName in libFilenamesList:
        if(not os.path.isfile(libName)):
            print("%s could not be found! Please check that the file path "\
                "was input correctly" % libName)
            sys.exit()

    if(not shutil.which(bowtiePath)):
        print("bowtie could not be found at the provided path: %s\nCorrect "\
            "before running again" % bowtiePath)
        sys.exit()

    if(not shutil.which(bowtieBuildPath)):
        print("bowtie-build could not be found at the provided path: %s\n"\
            "Correct before running again" % bowtieBuildPath)
        sys.exit()

    if(not shutil.which(einvertedPath)):
        print("einverted could not be found at the provided path: %s\n"\
            "Correct before running again" % einvertedPath)
        sys.exit()
    
    if(not shutil.which(perlPath)):
        print("perl could not be found at the provided path: %s\n"\
            "Correct before running again" % perlPath)
        sys.exit()


    ### Create the necessary folders if they don't already exist
    # Create a path for genome if it does not exist already
    if not os.path.isdir("genome"):
        os.mkdir('genome')
    # Create a path for the inverted repeat if it does not exist already
    if(not os.path.isdir("invertedRepeats")):
        os.mkdir("invertedRepeats")

    # If the user has filled the outputFolder option, check to see if it
    # has results from an older run and then delete them
    if(outputFolder):
        if(os.path.isdir("%s/libs" % outputFolder)):
            shutil.rmtree("%s/libs" % outputFolder)
        if(os.path.isdir("%s/images" % outputFolder)):
            shutil.rmtree("%s/images" % outputFolder)
        if(os.path.isfile("%s/finalAnnotatedCandidates.csv" % outputFolder)):
            os.remove("%s/finalAnnotatedCandidates.csv" % outputFolder)
        if(os.path.isfile("%s/preAnnotatedCandidates.csv" % outputFolder)):
            os.remove("%s/preAnnotatedCandidates.csv" % outputFolder)
        if(os.path.isfile("%s/preAnnotatedCandidates.fa" % outputFolder)):
            os.remove("%s/preAnnotatedCandidates.fa" % outputFolder) 

    ###########################################################################

    # Create a path for an output folder if it does not exist already
    # (Almost certainly shoul dnot as it would require the same run second)
    else:
        outputFolder = datetime.datetime.now().strftime(
            'output_%Y-%m-%d_%H-%M-%S')
    if not os.path.isdir(outputFolder):
        os.mkdir(outputFolder)
    if not os.path.isdir("%s/libs" % outputFolder):
        os.mkdir("%s/libs" % outputFolder)
    if not os.path.isdir("%s/images" % outputFolder):
        os.mkdir("%s/images" % outputFolder)

    LibList = []

    if(parallel):
        nproc = int(round(int(multiprocessing.cpu_count()*.5),1))
        pool = multiprocessing.Pool(nproc)

    # Create genome object
    GenomeClass = genome.Genome(genomeFilename, bowtieBuildPath)

    ##########################################################################

    ############### Find inverted repeats in genome file #####################

    ##########################################################################

    # If not set to run in parallel, run the sequential function
    # for einverted
    if(runEInvertedFlag):
        # Create an empty list for both the inverted repeat FASTA files
        # and alignment files
        IRFastaFilenamesList = []
        IRAlignmentFilenamesList = []

        # If parallel is set, run einverted using the parallel version
        if(parallel):
            print("Running einverted in parallel")

            res = pool.starmap_async(GenomeClass.runEinverted,
                zip(repeat(einvertedPath), GenomeClass.genomeSeqList,
                repeat(match), repeat(mismatch), repeat(gap), 
                repeat(threshold), repeat(maxRepLen)))

            results = res.get()

            # Loop through the results and add the inverted repeat filenames
            # to their respective lists
            for result in results:
                IRFastaFilenamesList.append(result[0])
                IRAlignmentFilenamesList.append(result[1])

        else:
            print("Running einverted sequentially")

            for entry in GenomeClass.genomeSeqList:
                IRName, IRSeq = GenomeClass.runEinverted(einvertedPath, 
                    entry, match, mismatch, gap, threshold, maxRepLen)

                IRFastaFilenamesList.append(IRName)
                IRAlignmentFilenamesList.append(IRSeq)

    # If einverted was not run, set the temp file lists to be just the list
    # of the merged final file so that we can create the IRDictByChr using the
    # previously merged file
    else:
        IRFastaFilenamesList = [GenomeClass.IRFastaFilename]
        IRAlignmentFilenamesList = [GenomeClass.IRAlignmentFilename]

    # Combine the inverted repeat temp files of the einverted runs
    # into one file
    GenomeClass.combineIRTempFiles(IRFastaFilenamesList,
        IRAlignmentFilenamesList, runEInvertedFlag)

    #########################################################################

    ######################## Map small RNAs to genome #######################
 
    #########################################################################

    precursorsWithDuplexDictByLib = {}
    filteredPrecursorsDict = {}
    candidatesByLibDict = {}

    # Populate candidatesByLibDict chromosomes with empty dictionaries
    for chrName, chrIndex in GenomeClass.chrDict.items():
        candidatesByLibDict[chrName] = {}

    for libraryFilename in libFilenamesList:
        libNameNoFolders = os.path.splitext(os.path.basename(
            libraryFilename))[0]

        print("Beginning to process %s." % libraryFilename)
        Lib = library.Library(libraryFilename, GenomeClass.chrDict)

        precursorsWithDuplexDictByLib[libNameNoFolders] = {}
        filteredPrecursorsDict[libNameNoFolders] = {}

        for chrName in sorted(GenomeClass.chrDict.keys()):
            precursorsWithDuplexDictByLib[libNameNoFolders][chrName] = {}
            filteredPrecursorsDict[libNameNoFolders][chrName] = {}

        # Map small RNAs to the genome
        print("Running bowtie on %s" % Lib.filename)
        funcStart = time.time()

        logFilename = Lib.mapper(GenomeClass.indexFilename, bowtiePath,
            nthreads)

        funcEnd = time.time()
        execTime = round(funcEnd - funcStart, 2)
        print("Time to run bowtie for %s: %s seconds" % \
            (Lib.mapFilename, execTime))

        print("Creating the mapped list for %s" % Lib.filename)
        funcStart = time.time()

        # Create a dictionary with the sequence of all tags that
        # map to a position on every chromosome
        Lib.createMappedList(GenomeClass.chrDict)

        funcEnd = time.time()
        execTime = round(funcEnd - funcStart, 2)
        print("Time to create the mappedList: %s seconds" % (execTime))
    
        #######################################################################

        ################# Map small RNAs to inverted repeats ##################

        #######################################################################

        print("Mapping sRNAs to the inverted repeats")

        funcStart = time.time()

        mappedTagsToPrecursors = []

        if(parallel):
            # Run mapSRNAsToIRs in parallel
            res = pool.starmap_async(mapSRNAsToIRs.mapSRNAsToIRs,
                zip(GenomeClass.IRDictByChr, Lib.mappedList,
                repeat(Lib.libDict)))

            mappedTagsToPrecursors = res.get()

        else:
            for i in range(len(GenomeClass.chrDict)):
                mappedTagsToPrecursors.append(mapSRNAsToIRs.mapSRNAsToIRs(
                    GenomeClass.IRDictByChr[i], Lib.mappedList[i], Lib.libDict))

        funcEnd = time.time()
        execTime = round(funcEnd - funcStart, 2)
        print("Time to map sRNAs to inverted repeats: %s seconds" % (execTime))

        print("Writing precursors to a file")

        # Create a file for all precursors to be written to that have at least
        # one sRNA that maps to both strands
        unfilteredFilename = "%s/libs/%s_all_precursors.txt" % (outputFolder,
            libNameNoFolders)

        mapSRNAsToIRs.writeUnfilteredPrecursors(unfilteredFilename,
            GenomeClass.chrDict, GenomeClass.IRDictByChr,
            mappedTagsToPrecursors)

        #######################################################################

        ################### Filter precursor candidates #######################

        #######################################################################

        print("Filtering candidate precursors")

        funcStart = time.time()

        # If we are running in parallel, run filterPrecursors in parallel.
        # Parallelize by chromosomes
        if(parallel):
            res = pool.starmap_async(filterPrecursors.filterPrecursors,
                zip(mappedTagsToPrecursors, GenomeClass.IRDictByChr,
                repeat(overhang)))

            results = res.get()

            for chrName in sorted(GenomeClass.chrDict.keys()):
                chrIndex = GenomeClass.chrDict[chrName]

                # Get the index of chrDict[chrName]
                precursorsWithDuplexDictByLib[libNameNoFolders][chrName] \
                     = results[chrIndex][0]
                filteredPrecursorsDict[libNameNoFolders][chrName] = \
                    results[chrIndex][1]

        # If running sequentially, run filterPrecursors sequentially
        else:
            for chrName in sorted(GenomeClass.chrDict.keys()):
                # Get the index of each chromosome that will be processed
                # sequentially
                chrIndex = GenomeClass.chrDict[chrName]
                precursorList = mappedTagsToPrecursors[chrIndex]
                IRDict = GenomeClass.IRDictByChr[chrIndex]

                precursorsWithDuplexDictByLib[libNameNoFolders][chrIndex], \
                    filteredPrecursorsDict[libNameNoFolders][chrName] = \
                    filterPrecursors.filterPrecursors(precursorList, IRDict,
                    overhang)

        funcEnd = time.time()
        execTime = round(funcEnd - funcStart, 2)
        print("Time to map filter inverted repeats: %s seconds" % (execTime))

        ###
        # Prior to writing this library's results, add its miRNAs and
        # corresponding precursors to a dictionary

        # Loop through each chromosome of the final candidates dictionary
        # for this library
        for chrName, subFilteredPrecursorsDict in \
                filteredPrecursorsDict[libNameNoFolders].items():

            # Loop through each duplex in the precursor and add it to the 
            # dictionary tracking which library it has been found in
            for precursorName, duplexDict in subFilteredPrecursorsDict.items():
                if(precursorName not in candidatesByLibDict[chrName]):
                    candidatesByLibDict[chrName][precursorName] = {} 

                for mirCandidate in duplexDict.keys():
                    if(mirCandidate not in candidatesByLibDict[chrName]\
                            [precursorName]):
                        candidatesByLibDict[chrName][precursorName]\
                            [mirCandidate] = []

                    candidatesByLibDict[chrName][precursorName]\
                        [mirCandidate].append(libNameNoFolders)

    
        # Create a file for all precursors that have been identified as having
        # a valid miRNA:miRNA* duplex to be written to
        filteredFilename = "%s/libs/%s_candidate_precursors.txt" % (
            outputFolder, libNameNoFolders)

        funcStart = time.time()
        filterPrecursors.writeFilteredPrecursors(filteredFilename,
            GenomeClass.chrDict, GenomeClass.IRDictByChr,
            filteredPrecursorsDict[libNameNoFolders])

    filterPrecursors.writeCandidates(outputFolder, candidatesByLibDict,
        filteredPrecursorsDict, GenomeClass.IRDictByChr, libFilenamesList,
        GenomeClass.chrDict, GenomeClass.genomeSeqList, perlPath)

    ##########################################################################

    ################### Annotate candidate miRNAs ############################

    ##########################################################################
    
    print("Annotating candidate miRNAs")

    funcStart = time.time()

    queryMirnasFilename = "%s/preAnnotatedCandidates.fa" % outputFolder

    # Check to see if the BLAST database needs to be updated
    updateFlag = annotateCandidates.checkNeedUpdateByDate(
        subjectSequencesFilename, dbFilename)

    # Update the blast database if updateFlag is true
    if(updateFlag):
        # Create the database from the file holding the subject sequences
        localStartTime = time.time()
        dbName = annotateCandidates.createBlastDB(subjectSequencesFilename,
            dbFilename)

    # BLAST query miRNAs to known miRNAs
    localStartTime = time.time()
    print("Performing BLAST")
    blastFilename = annotateCandidates.blastMirnas(subjectSequencesFilename,
        dbFilename, queryMirnasFilename)

    # Add field for the subject and query sequences in the BLAST output
    # because these sequences are not within by default
    print("Adding sequences to output file")
    annotateCandidates.addSequencesToOutput(queryMirnasFilename,
        subjectSequencesFilename)

    # Read the BLAST results into a dictionary for quick querying
    blastDict = annotateCandidates.readBlastResults(blastFilename)

    # Create a dictionary of either the known miRNAs that the candidate
    # miRNAs are equal to, or the miRNA families and species that the
    # candidate miRNA is highly similar to
    similarityDict = annotateCandidates.createSimilarityDict(blastDict,
        organism)

    numLibs = len(libFilenamesList)

    # Properly annotate the candidate miRNAs with the data in similarityDict
    annotateCandidates.annotateCandidates(outputFolder, similarityDict,
        organism, numLibs)


    funcEnd = time.time()
    execTime = round(funcEnd - funcStart, 2)
    print("Time to annotate candidate miRNAs: %s seconds" % (execTime))

    progEnd = time.time()
    execTime = round(progEnd - progStart, 2)

    print("Total runtime was %s seconds" % execTime)

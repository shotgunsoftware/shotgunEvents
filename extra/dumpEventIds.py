#!/usr/bin/python
try:
    import cPickle as pickle
except ImportError:
    import pickle
import sys
import pprint

def main( ) :
	eventIdFile = sys.argv[1]
	with open(eventIdFile) as fh :
		eventIdData = pickle.load(fh)
		pprint.pprint( eventIdData )
	return 0
	
if __name__ == '__main__':
	sys.exit( main() )

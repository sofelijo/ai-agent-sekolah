"""Run the durable original-to-demo worker."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import dotenv_values
from demo_replication import run

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    run(dotenv_values(args.project/'.env'),once=args.once)

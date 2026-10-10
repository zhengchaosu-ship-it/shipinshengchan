"""在执行生产模块前加入父入口的Windows Job。"""
import argparse
import runpy
import sys

from .process_job import join


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--job-name',required=True)
    parser.add_argument('--module',required=True)
    parser.add_argument('--config',required=True)
    args=parser.parse_args()
    join(args.job_name)
    if sys.stdin.readline().strip()!='START': raise RuntimeError('SERVER_OWNER_NOT_READY')
    sys.argv=[args.module,'--config',args.config]
    runpy.run_module(args.module,run_name='__main__')


if __name__=='__main__':main()

#!/bin/sh
base_dir=$(dirname $0)
export PYTHONPATH=${base_dir}/../shotgun_api:${PYTHONPATH} && ${base_dir}/shotgunEventDaemon.py "$@"


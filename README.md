still a work in progress but the steps are roughly:

```shell
# Download the benchmark tar files
aws s3 sync s3://ngiab-benchmark ~/.ngiab/bench

# clone this repo
git clone https://github.com/ngiab/ngiab-bench.git

# build the docker image (replace the FROM line with whatever ngiab base image you want to use)
docker build -t ngiab-bench .

# run the benchmark and mount the data to /ngen/bench
docker run -it -v ~/.ngiab/bench:/ngen/bench ngiab-bench

# the summary.py will be run in the container but it might need rerunning externally if it didn't pick up the system hardware properly
# it tries to use dmidecode nvme-cli smartctl lshw, install as many as you like
uv run --with pandas --with psutil summary.py

#!/bin/bash

# Base directories
BENCHMARK_DIR="/ngen/bench"
DATA_DIR="/ngen/ngen/data"
CONFIG_DIR="$DATA_DIR/config"

# Parallel unzip function
punzip() {
    if [ $# -lt 1 ] || [ $# -gt 2 ]; then
        echo "Usage: punzip <filename.tar.gz> [output_dir]"
        return 1
    fi

    local output_dir="${2:-.}"
    mkdir -p "$output_dir"
    pigz -dc "$1" | tar xf - --strip-components=1 -C "$output_dir"
}

# Function to generate partitions
generate_partitions() {
    python /dmod/utils/partitioning/local_only_partitions.py "$1" "$2" "."
}

# Function to process a single tarball
process_tarball() {
    local tarball="$1"
    local duration="$2"
    local ops="$3"
    local gage=$(basename "$tarball" .tar.gz)

    echo "Processing: $duration/$ops/$gage"

    # Clean data directory
    echo "Cleaning data directory..."
    rm -rf "$DATA_DIR"/*

    # Extract tarball using parallel unzip
    echo "Extracting $tarball..."
    punzip "$tarball" "$DATA_DIR"

    # Find and replace routing with no_routing in troute.yaml
    echo "Modifying troute.yaml..."
    sed -i 's/routing/no_routing/g' "$CONFIG_DIR/troute.yaml"

    # Find the gpkg file
    gpkg=$(find "$CONFIG_DIR" -name "*.gpkg" | head -1)
    if [ -z "$gpkg" ]; then
        echo "Error: No .gpkg file found in $CONFIG_DIR"
        return 1
    fi
    echo "Found gpkg: $gpkg"

    # Generate partitions
    echo "Generating partitions..."
    cd "$DATA_DIR"
    procs=$(nproc)
    procs=$(generate_partitions "$gpkg" "$procs" | tail -n 1)
    echo "Created $procs partitions"

    # Create output directory for this run
    output_dir="$BENCHMARK_DIR/results/${duration}_${ops}_${gage}"
    mkdir -p "$output_dir"

    # Run mpirun with hyperfine
    echo "Benchmarking mpirun..."
    hyperfine --warmup 1 \
        --runs 3 \
        --export-json "$output_dir/mpirun_benchmark.json" \
        --export-markdown "$output_dir/mpirun_benchmark.md" \
        "mpirun -n $procs /dmod/bin/ngen-parallel $gpkg all $gpkg all $CONFIG_DIR/realization.json $(pwd)/partitions_$procs.json"

    # Run troute with hyperfine
    echo "Benchmarking troute..."
    hyperfine --warmup 1 \
        --runs 3 \
        --setup "rm -rf /ngen/ngen/data/outputs/parquet/*.*" \
        --export-json "$output_dir/troute_benchmark.json" \
        --export-markdown "$output_dir/troute_benchmark.md" \
        "python -m nwm_routing -f ./config/troute.yaml"

    echo "Completed: $duration/$ops/$gage"
    echo "Results saved to: $output_dir"
    echo "----------------------------------------"
    cd -
}

# Main script
main() {

    # Change to ngiab-benchmark directory
    cd $BENCHMARK_DIR
    mkdir -p $DATA_DIR

    # Process all durations
    for duration in 1d 1m 1y 10y; do
    # for duration in 1d ; do
        echo "=== Processing duration: $duration ==="

        # Get all operation directories and sort numerically
        ops_dirs=($(find "$duration" -mindepth 1 -maxdepth 1 -type d | grep -E '/[0-9]+$' | sort -t/ -k2 -n))

        # Process each operation directory
        for ops_dir in "${ops_dirs[@]}"; do
        # for ops_dir in 1d/1; do
            ops=$(basename "$ops_dir")

            # Find the tarball in this directory
            tarball=$(find "$ops_dir" -name "*.tar.gz" | head -1)

            if [ -n "$tarball" ]; then
                process_tarball "$tarball" "$duration" "$ops"
            else
                echo "Warning: No tarball found in $ops_dir"
            fi
        done
    done

    echo "=== Benchmarking complete ==="
    echo "All results saved to: $BENCHMARK_DIR"

    uv run --with pandas --with psutil /ngen/summary.py
}

# Run the main function
main

#!/usr/bin/env python3

import json
import os
import platform
import re
import subprocess
from pathlib import Path

import pandas as pd
import psutil

DOCKER_BENCHMARK_DIR = Path("/ngen/bench/results")
EXTERNAL_BENCHMARK_DIR = Path("~/.ngiab/bench/results").expanduser()

# Check if running in Docker
in_docker = os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")
if in_docker:
    BENCHMARK_DIR = DOCKER_BENCHMARK_DIR
else:
    BENCHMARK_DIR = EXTERNAL_BENCHMARK_DIR


def parse_result_dir(dirname):
    """Extract duration, ops, and gage from directory name"""
    match = re.match(r"(\d+[dmy])_(\d+)_(.+)", dirname)
    if match:
        return match.groups()
    return None, None, None


def load_hyperfine_results(json_file):
    """Load hyperfine JSON and extract mean time"""
    try:
        with open(json_file, "r") as f:
            data = json.load(f)
            return data["results"][0]["mean"]
    except:
        return None


def get_system_info():
    """Gather system and hardware information"""
    info = {}

    # CPU detailed info
    try:
        # Get CPU name from lscpu
        lscpu = subprocess.check_output(["lscpu"]).decode()
        for line in lscpu.split("\n"):
            if "Model name:" in line:
                info["CPU Model"] = line.split(":", 1)[1].strip()
            elif "CPU MHz:" in line:
                info["CPU Clock"] = f"{float(line.split(':')[1].strip()):.0f} MHz"
            elif "L1d cache:" in line:
                info["L1d Cache"] = line.split(":")[1].strip()
            elif "L1i cache:" in line:
                info["L1i Cache"] = line.split(":")[1].strip()
            elif "L2 cache:" in line:
                info["L2 Cache"] = line.split(":")[1].strip()
            elif "L3 cache:" in line:
                info["L3 Cache"] = line.split(":")[1].strip()
    except:
        info["CPU Model"] = platform.processor() or "Unknown"

    info["CPU Cores"] = psutil.cpu_count(logical=False)
    info["CPU Threads"] = psutil.cpu_count(logical=True)

    # Memory detailed info
    mem = psutil.virtual_memory()
    info["Memory Total"] = f"{mem.total / (1024**3):.1f} GB"

    if not in_docker:
        try:
            # Get memory details from dmidecode (requires sudo)
            dmidecode = subprocess.check_output(
                ["sudo", "dmidecode", "-t", "memory"], stderr=subprocess.DEVNULL
            ).decode()
            speeds = []
            types = []
            sizes = []

            for line in dmidecode.split("\n"):
                if "Type:" in line and "DDR" in line:
                    types.append(line.split(":")[1].strip())
                elif "Speed:" in line and "MT/s" in line:
                    speeds.append(line.split(":")[1].strip())
                elif "Size:" in line and ("GB" in line or "MB" in line):
                    if "Volatile" in line:
                        continue
                    sizes.append(line.split(":")[1].strip())

            if types and speeds:
                info["Memory Type"] = types[0] if len(set(types)) == 1 else ", ".join(set(types))
                info["Memory Speed"] = (
                    speeds[0] if len(set(speeds)) == 1 else ", ".join(set(speeds))
                )
                if sizes:
                    info["Memory Config"] = (
                        f"{len(sizes)}x{sizes[0]}" if len(set(sizes)) == 1 else ", ".join(sizes)
                    )
        except:
            pass

    # OS
    info["OS"] = f"{platform.system()} {platform.release()}"

    # Drive detailed info
    try:
        # Get device for benchmark dir
        df_output = subprocess.check_output(["df", BENCHMARK_DIR]).decode()
        device = df_output.split("\n")[1].split()[0]

        # Get filesystem type
        fs_output = subprocess.check_output(["df", "-T", BENCHMARK_DIR]).decode()
        info["Filesystem"] = fs_output.split("\n")[1].split()[1]

        # Try to get drive model
        if "/dev/" in device:
            # Remove partition number to get base device
            base_device = re.sub(r"\d+$", "", device)  # Remove trailing numbers
            base_device = re.sub(r"p$", "", base_device)  # Remove pX for nvme drives
            base_device = re.sub(r"n\d+$", "", base_device)  # Remove trailing n

            # For NVMe drives, use nvme list command
            if "nvme" in base_device:
                try:
                    nvme_output = subprocess.check_output(
                        ["nvme", "list"], stderr=subprocess.DEVNULL
                    ).decode()
                    lines = nvme_output.strip().split("\n")
                    for line in lines:  # Skip header
                        if base_device.split("/")[-1] in line:
                            # Split by multiple spaces
                            line = re.sub(r"^[^\s]+\s+[^\s]+\s+[^\s]+\s+", "x  x  x  ", line)
                            parts = re.split(r"\s{2,}", line.strip())
                            if len(parts) >= 4:
                                info["Drive Model"] = parts[3]  # Model column
                                info["Drive Type"] = "NVMe SSD"
                                info["Drive Interface"] = "NVMe"
                                # Get capacity from Usage column
                                info["Drive Capacity"] = re.findall(r"\s+[0-9\.]+\s+[MTG]B", line)[
                                    -1
                                ].strip()
                                break
                except:
                    pass

            # Fallback methods if not in Docker or nvme list fails
            if "Drive Model" not in info and not in_docker:
                try:
                    # Method 1: smartctl
                    smart = subprocess.check_output(
                        ["sudo", "smartctl", "-i", base_device], stderr=subprocess.DEVNULL
                    ).decode()
                    for line in smart.split("\n"):
                        if "Device Model:" in line or "Model Number:" in line:
                            info["Drive Model"] = line.split(":", 1)[1].strip()
                        elif "Rotation Rate:" in line:
                            if "Solid State" in line:
                                info["Drive Type"] = "SSD"
                            else:
                                info["Drive Type"] = f"HDD ({line.split(':')[1].strip()})"
                except:
                    pass

                # Method 2: lshw (very detailed)
                try:
                    lshw = subprocess.check_output(
                        ["sudo", "lshw", "-class", "disk", "-class", "storage"],
                        stderr=subprocess.DEVNULL,
                    ).decode()
                    # Parse lshw output for NVMe/disk info
                    finish_up = False
                    for line in lshw.split("\n"):
                        if "product:" in line:
                            info["Drive Model"] = line.split(":", 1)[1].strip()
                        elif "vendor:" in line and "Drive Model" in info:
                            info["Drive Vendor"] = line.split(":", 1)[1].strip()
                        elif "size:" in line and "Drive Model" in info:
                            info["Drive Size"] = line.split(":", 1)[1].strip()
                        if finish_up and "*-" in line and "namespace" not in line:
                            break
                        elif "logical name:" in line and base_device.split("/")[-1] in line:
                            finish_up = True
                except:
                    pass

            # Method 3: lsblk (should work in Docker)
            try:
                if "Drive Model" not in info:
                    lsblk = subprocess.check_output(
                        ["lsblk", "-o", "NAME,MODEL,ROTA,SIZE", "-n", base_device],
                        stderr=subprocess.DEVNULL,
                    ).decode()
                    parts = lsblk.strip().split()
                    if len(parts) >= 2 and parts[1] != "":
                        info["Drive Model"] = " ".join(parts[1:-2]) if len(parts) > 3 else parts[1]
                        if len(parts) >= 3:
                            info["Drive Type"] = "HDD" if parts[-2] == "1" else "SSD"
                        if len(parts) >= 4:
                            info["Drive Capacity"] = parts[-1]
            except:
                pass
    except:
        info["Drive"] = "Unknown"

    # Docker info
    try:
        docker_version = subprocess.check_output(["docker", "--version"]).decode().strip()
        info["Docker"] = docker_version

        # Check if running in container
        if in_docker:
            info["Environment"] = "Inside Docker Container"
            # Try to get container info
            try:
                hostname = subprocess.check_output(["hostname"]).decode().strip()
                info["Container Hostname"] = hostname
            except:
                pass
        else:
            info["Environment"] = "Host System"
    except:
        info["Docker"] = "Not detected"
        info["Environment"] = "Docker Container" if in_docker else "Host System"

    return info


def main():
    results = []

    # Walk through benchmark directory
    if not os.path.exists(BENCHMARK_DIR):
        print(f"Error: Benchmark directory '{BENCHMARK_DIR}' does not exist")
        return

    for dirname in os.listdir(BENCHMARK_DIR):
        dirpath = Path(BENCHMARK_DIR) / dirname
        if dirpath.is_dir():
            duration, ops, gage = parse_result_dir(dirname)
            if duration and ops:
                # Load benchmark results
                mpirun_time = load_hyperfine_results(dirpath / "mpirun_benchmark.json")
                troute_time = load_hyperfine_results(dirpath / "troute_benchmark.json")

                results.append(
                    {
                        "Duration": duration,
                        "Operations": int(ops),
                        "Gage": gage,
                        "MPI Runtime (s)": round(mpirun_time, 3) if mpirun_time else "N/A",
                        "Troute Runtime (s)": round(troute_time, 3) if troute_time else "N/A",
                        "Total Runtime (s)": round(mpirun_time + troute_time, 3)
                        if mpirun_time and troute_time
                        else "N/A",
                    }
                )

    if not results:
        print("No benchmark results found")
        return

    # Create DataFrame and sort
    df = pd.DataFrame(results)
    df = df.sort_values(["Operations", "Duration"])

    # Get system info
    sys_info = get_system_info()

    # Print system info
    print("\n=== SYSTEM INFORMATION ===")
    for key, value in sys_info.items():
        print(f"{key}: {value}")

    # Display table grouped by operations
    print("\n=== BENCHMARK RESULTS (Grouped by Operations) ===\n")
    print(df.to_string(index=False))

    # Save as CSV with metadata
    csv_path = Path(BENCHMARK_DIR) / "benchmark_summary.csv"

    # Write metadata as comments at top of CSV
    with open(csv_path, "w") as f:
        f.write("# System Information\n")
        for key, value in sys_info.items():
            f.write(f"# {key}: {value}\n")
        f.write("#\n")

    # Append the data
    df.to_csv(csv_path, mode="a", index=False)
    print(f"\nCSV saved to: {csv_path}")


if __name__ == "__main__":
    main()

FROM joshcu/ngiab
# install cargo
RUN dnf install -y pigz cargo hdparm dmidecode lshw nvme-cli
RUN cargo install hyperfine
COPY bench.sh /ngen/bench.sh
COPY summary.py /ngen/summary.py
CMD ["--help"]
ENTRYPOINT [ "/ngen/bench.sh" ]

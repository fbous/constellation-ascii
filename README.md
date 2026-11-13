# constellation-ascii

Render any of the 88 constellations as ASCII art in your terminal — optionally
with stick-figure lines, brightness shading and the naked-eye planets currently
in the field. Pure Python stdlib, no dependencies.

## Install

```bash
pipx install constellation-ascii
```

Or just run the single file: `python3 constellation_ascii.py orion`.

## Usage

```bash
constellation-ascii orion
constellation-ascii "Ursa Major" -l -c -w 80
constellation-ascii lyra -p -u        # with today's planets, as symbols
constellation-ascii -L                # list names
```

Run `constellation-ascii -h` for all options. `NO_COLOR` is respected.

## Login banner

Name a host after a constellation and it can render its own banner:

```bash
sudo pipx install --global constellation-ascii
sudo tee /etc/cron.d/constellation-motd <<'EOF'
PATH=/usr/local/bin:/usr/bin:/bin
0 4 * * * root constellation-ascii "$(hostname -s)" -b -c -p -a 2 -w 80 > /etc/motd.new && mv /etc/motd.new /etc/motd
@reboot   root constellation-ascii "$(hostname -s)" -b -c -p -a 2 -w 80 > /etc/motd.new && mv /etc/motd.new /etc/motd
EOF
```

`-p` adds today's planets, hence the daily refresh; without it, run the
command once. `-a 2` pins the cell aspect so nothing queries a terminal.

## Data

On first run, star data is downloaded and cached in
`${XDG_CACHE_HOME:-~/.cache}/constellation-ascii`:

- [HYG Database](https://github.com/astronexus/HYG-Database) by David Nash
  (astronexus) — CC BY-SA 4.0
- [Stellarium sky cultures](https://github.com/Stellarium/stellarium-skycultures)
  (western) — constellation figures

Planet positions are computed offline. The data is not bundled with this
package; its licenses apply to it separately.

## License

MIT — see [LICENSE](LICENSE).

# WRF-SFIRE local baseline run

Date: 2026-10-03 (America/Los_Angeles)

## Result

The idealized `test/em_fire/hill` case completed successfully with the
WRF-SFIRE implementation selected by `ifire = 1`.

Completion marker:

```text
d01 0001-01-01_00:05:00 wrf: SUCCESS COMPLETE WRF
```

Process exit status: `0`

Measured runtime and memory:

```text
Elapsed wall time: 2:24.73
User CPU time: 138.77 seconds
System CPU time: 3.84 seconds
Maximum resident set size: 198620 KiB
```

The run produced 61 output times on a 420 x 420 fire subgrid. Verified
fire-related fields include `TIGN_G`, `LFN`, `FIRE_AREA`, `FIRE_HFX`,
`FGRNHFX`, `FGRNQFX`, `FUEL_FRAC`, and `ROS`.

## Repository provenance

```text
Fork:     https://github.com/erfwn81/WRF-SFIRE
Origin:   https://github.com/erfwn81/WRF-SFIRE.git
Upstream: https://github.com/openwfm/WRF-SFIRE.git
Commit:   9801186f3ef8a500ec106aecfdcb051c4d1e38db
Branch:   master
```

The local checkout is shallow, but the exact commit is recorded and the fork
on GitHub retains repository history.

## Local environment

```text
Operating system: Ubuntu 26.04.1 LTS (Resolute Raccoon)
Architecture: x86_64
CPU threads: 32
RAM: 30 GiB
GNU Fortran: 15.2.0
NetCDF-C: 4.9.3
NetCDF-Fortran: 4.6.2
Build type: GNU serial, configure option 32
Nesting: basic, option 1
NetCDF mode: classic
```

## Ubuntu 26.04 build compatibility settings

The generated `configure.wrf` required two local compatibility changes.
They do not change model physics.

1. GCC 15 defaults to C23, while this WRF branch contains legacy K&R-style C.
   The following flag was added to `CFLAGS_LOCAL` and `CC_TOOLS_CFLAGS`:

   ```text
   -std=gnu89
   ```

2. Ubuntu packages NetCDF-Fortran separately. The generated linker settings
   omitted it, so `LIB_EXTERNAL` was extended with:

   ```text
   -L/usr/lib/x86_64-linux-gnu -lnetcdff -lnetcdf
   ```

Running `./clean -a` or re-running `./configure` regenerates `configure.wrf`;
these two local settings must then be applied again.

## Configuration and build commands

From the repository root:

```bash
git submodule update --init --recursive --depth 1

printf '32\n1\n' | env \
  NETCDF=/usr NETCDF_classic=1 \
  CC=gcc CXX=g++ FC=gfortran F77=gfortran F90=gfortran \
  OMP_NUM_THREADS=1 \
  ./configure > configure.log 2>&1
```

After applying the two compatibility settings above to `configure.wrf`:

```bash
env NETCDF=/usr NETCDF_classic=1 \
  CC=gcc CXX=g++ FC=gfortran F77=gfortran F90=gfortran \
  OMP_NUM_THREADS=1 \
  ./compile em_fire -j 4 > compile_em_fire.log 2>&1
```

The required executables are:

```text
main/ideal.exe
main/wrf.exe
```

The legacy `create_links.sh` step may report that test links already exist.
This is harmless when both executables exist and the links resolve to them.

The optional `diffwrf` diagnostic utility also failed to link during the first
pass because of the same missing NetCDF-Fortran flags. This does not affect the
`ideal.exe` or `wrf.exe` baseline executables.

## Run commands

The repository's top-level `hill_simple` link currently selects `ifire = 2`.
To exercise the repository's WRF-SFIRE implementation (`ifire = 1`), the run
used the dedicated `hill` case:

```bash
cd test/em_fire/hill
grep -n ifire namelist.input
./ideal.exe > ideal.log 2>&1
/usr/bin/time -v ./wrf.exe > wrf.log 2> wrf_time.log
```

Validation commands:

```bash
tail -n 30 ideal.log
tail -n 30 wrf.log
grep 'SUCCESS COMPLETE' ideal.log wrf.log
ncdump -h wrfout_d01_0001-01-01_00:00:00 | less
```

## Generated artifacts

Run directory:

```text
/home/erfan/Documents/Projects/WRF-SFIRE/source/test/em_fire/hill
```

Important files:

```text
ideal.log
wrf.log
wrf_time.log
wrfinput_d01
wrfout_d01_0001-01-01_00:00:00
```

The history file is approximately 2.8 GiB because the five-minute case writes
61 high-resolution time records. Plan storage before generating ensembles.

## Next recommended milestone

Do not begin a large ML dataset yet. First create plots for `FIRE_AREA`, `LFN`,
`TIGN_G`, `ROS`, `FIRE_HFX`, near-surface wind, and terrain at selected times.
Then rerun one controlled sensitivity experiment (for example, change only the
initial wind) and verify that fire spread responds physically.

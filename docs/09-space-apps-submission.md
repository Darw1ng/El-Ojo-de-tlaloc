# Space Apps 2026 submission draft

Draft text for the project submission form, in English as the rules require.
Fields follow the 2025 Project Submission Guide; check them against the 2026
guide when it is published and fill in the two links.

---

**Project name:** Water's Dance — El Ojo de Tláloc

**Challenge:** Dancing with the SARs

**Team:** Amigos de Timmy (Universal Event)

**Project demo:** `<link to demo_en.mp4 or slides>`

**Final project:** https://darw1ng.github.io/El-Ojo-de-tlaloc/ (story map) ·
https://github.com/Darw1ng/El-Ojo-de-tlaloc (code)

## High-level summary

Water's Dance is an open-source, bilingual (Spanish/English) interactive story
map and explorer built on ten real NISAR L-band passes over the Veracruz–Boca
del Río metropolitan area, Mexico, during the 2026 rainy season (June 25 –
October 23). It turns radar backscatter into things a resident or a city
planner can read: where open water appears and disappears, how soil moisture
rises after rain, why the city's protected interdune lagoons look like
vegetation to the radar, and why a 12-day revisit cannot catch an urban flood
that drains in hours. It connects those observations to our stochastic flood
forecast, where soil moisture is the initial condition that decides whether
60 mm of rain soaks in or runs into the street.

## Project details

**What it does.** A scroll-driven story in twelve chapters, followed by a free
explorer. The explorer has nine layers (HH·HV composite, HH, HV, open water,
change against the season median, soil-moisture index, water permanence,
lagoons by radar signature, and a 3D hexagon grid). It also has a time slider
over the ten passes with daily rainfall, a before/after swipe between any two
dates, and a click-anywhere popup with that pixel's HH/HV time series.

**How it works.**
1. `scripts/nisar_gcov.py` searches the ASF catalog and reads only the
   metropolitan window (2,148 × 2,365 pixels at 10 m) from each remote 4.8 GB
   GCOV HDF5 file with `earthaccess`. Ten dates take about eight minutes
   instead of a 47 GB download.
2. `scripts/nisar_productos.py` applies a Lee speckle filter and a relative
   radiometric normalization against stable urban targets. The provisional
   products drifted about 1 dB between dates, and the city revealed it. It
   then thresholds open water at the histogram valley (HH < −14.8 dB,
   HV < −19.8 dB), masks the sea, beach and runways, and computes per-pixel
   change and a change-detection soil-moisture index. Finally it crosses
   everything with NASA POWER rainfall and with OpenStreetMap lagoons,
   schools, clinics and emergency services, on the project's hexagonal grid.
3. The web app (`frontend/nisar/`) is plain HTML/CSS/JS with MapLibre GL JS over OpenStreetMap. It
   needs no build step and runs as a static site.

**What we found.**
- Inland open water ranged from 1.1 to 2.2 km² per pass. Most of the change
  is at the northern end of the Mandinga lagoon system, between 1.0 and
  1.45 km².
- The soil-moisture index went from 0.39 (August 12) to 0.59 (September 17).
  It tracks the previous three days of rain moderately (r = 0.36).
- None of the 58 mapped lagoons shows an open-water signature: 29 look like
  vegetation over water and 29 are mixed. Tarimoya lagoon brightened 2.3 dB
  from June to late September, consistent with water rising under
  vegetation. This is a hypothesis to check in the field.
- No school, clinic or emergency service was within 200 m of temporary open
  water on any pass. Urban floods are faster than the revisit, which is
  exactly why radar soil moisture belongs inside a forecast.

**Limits we state openly.** The products are provisional, so the
normalization also removes any scene-wide signal. Rainfall comes from a single
half-degree NASA POWER point. The moisture index is relative, not volumetric.
The lagoon interpretation has not been checked in the field.

**Tools.** Python (numpy, scipy, scikit-image, h5py, rasterio, earthaccess,
Pillow), FastAPI for the forecasting backend, MapLibre GL JS, Leaflet, HyperFrames for the
demo video, ffmpeg.

## NASA data

- NISAR L2 GCOV (NISAR_L2_GCOV_V1), track 163 ascending, frame 11, mode 4005,
  HH/HV, ten dates, via the Alaska Satellite Facility DAAC
  (https://search.asf.alaska.edu). The exact granule IDs are in
  `frontend/nisar/datos/meta.json`.
- NASA POWER daily precipitation (PRECTOTCORR), https://power.larc.nasa.gov.

## Space agency partner and other data

- NISAR is a joint NASA–ISRO mission (L-band by NASA/JPL, S-band by ISRO).
- OpenStreetMap contributors (ODbL): lagoons, wetlands, runways, schools,
  health and emergency facilities.
- Ramsar Sites Information Service, site 1450 (Sistema de Lagunas
  Interdunarias de la Ciudad de Veracruz).
- Esri World Imagery (satellite base map).

## Use of artificial intelligence

We used Anthropic's Claude (Claude Code) as a coding and writing assistant to
write the download and processing scripts, build the web app, draft the
bilingual story text and this summary, and assemble the demo video. Every
number in the story is computed from the NISAR, NASA POWER and OpenStreetMap
data by the scripts in the repository. No imagery, map or data value was
generated by AI. The team reviewed the method, the results and the stated
limits.

## References

- NISAR mission: https://nisar.jpl.nasa.gov
- ASF NISAR data: https://asf.alaska.edu
- Lee, J.-S. (1980). Digital image enhancement and noise filtering by use of local statistics.
- Wagner, W. et al. (1999). A method for estimating soil moisture from ERS scatterometer and soil data (change detection).
- Ramsar site 1450: https://rsis.ramsar.org/ris/1450

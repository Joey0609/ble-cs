# Licensing and third-party components

## Project-authored material

- Software source code is MIT licensed under [LICENSE](LICENSE). C and other
  source files use the `SPDX-License-Identifier: MIT` marker where supported.
- Project-authored documentation and design material is CC BY 4.0 under
  [LICENSE-DOCS.md](LICENSE-DOCS.md).
- `scripts/b205mini_2403_spectrum.py` is an exception: it retains its existing
  `SPDX-License-Identifier: GPL-3.0` notice. Its license is not changed by the
  repository MIT license.

Documentation licensing does not apply to imported Bluetooth standards,
vendor manuals, third-party papers, or other externally authored content in
`docs/`; those items retain their original license and attribution. In
particular, a document is not relicensed just because it is stored in this
repository.

## Zephyr and nRF Connect SDK

This repository does not vendor the Zephyr or nRF Connect SDK source trees.
Firmware builds use those dependencies from the separately installed NCS
workspace. The repository's `tests/**/include/zephyr/` files are local test
stubs, not copied Zephyr implementation files.

Using Zephyr APIs does not by itself change this project's source license to
Apache-2.0. Zephyr's own files are Apache-2.0 unless a file or component states
another license. Any Zephyr/NCS source copied into this repository must retain
its upstream copyright, license identifier, and applicable notices; such files
are not automatically MIT licensed. When distributing Apache-2.0 components,
follow its redistribution conditions: provide the license, retain relevant
copyright/patent/trademark/attribution notices, mark modified upstream files,
and reproduce applicable NOTICE attributions. For binary distributions,
required notices belong in accompanying documentation or other materials.

The distinction matters when distributing firmware: a firmware image built
with NCS incorporates or links upstream components. Follow the license and
notice requirements of every component included in that image. NCS is
multi-repository and its components may have different licenses and conditions;
check the installed release's per-repository `LICENSE` files and source SPDX
headers for the exact image. The nRF Connect SDK manifest repository has its
own Nordic license, and some Nordic-licensed components carry additional use
conditions. The existence of this repository's MIT license does not replace
those third-party terms.

The Zephyr project states that Zephyr is Apache-2.0 licensed and documents
component-level exceptions in its [licensing documentation](https://docs.zephyrproject.org/latest/LICENSING.html).
Nordic's [nRF Connect SDK repository](https://github.com/nrfconnect/sdk-nrf)
also has its own root license and per-component license information.

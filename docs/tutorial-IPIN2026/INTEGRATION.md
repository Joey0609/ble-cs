# SensWear · IPIN 2026 unified tutorial

The default index.html presents one continuous tutorial with a shared SensWear theme: dark teal background, Outfit headings, consistent typography, card styling, diagram palette, breadcrumbs, and slide controls.

The combined delivery has 54 main slides and 19 supplementary slides. SPEAKER-GUIDE.html and integration/run-of-show.json allocate 90 minutes to the main route. No presentation timings appear on audience slides.

## Content preservation

All substantive original technical content is retained: 18 slides covering Bluetooth localization, ACL setup/events/negotiation, phase and RTT, Bluetooth Channel Sounding, step modes, toolchain, and hosted/hostless operation. Text, equations, diagram labels, coordinates, paths, and timing geometry are preserved. Styling is applied at rendering time, including recoloring vector artwork to the shared palette.

The original cover, agenda, and Questions closing slide are omitted from the combined delivery, which has one opening, roadmap, and handover. All original files remain unchanged on disk. The original deck, including its front/back matter and white theme, remains accessible through technical-original.html.

## Present

Run npm start as before, or double-click START-INTEGRATED.cmd. The current server default is http://127.0.0.1:8023/tutorial-IPIN2026/. HTTP is required to load slide fragments. All scripts, fonts, images, and math rendering assets for the unified presentation are local; no Internet connection is required.

- Right Arrow, Space, or Page Down: advance through the continuous sequence. Left Arrow, Shift+Space, or Page Up: go back.
- Header breadcrumb: jump between Why indoors, SensWear, Channel Sounding, Positioning, and Hands-on. Supplementary slides add Reference.
- N: presenter notes and revised schedule. S: separate presenter window. O / Esc: overview. F: fullscreen.
- RTT, phase, and geometry demonstrations remain interactive. Click app screenshots to enlarge them.

## Organization

integration/slide-order.json controls the combined sequence. Original technical fragments remain in slides/; added SensWear fragments remain in senswear/slides/. The original vertical groups are presented as consecutive horizontal slides, allowing examples to sit beside the concepts they demonstrate. IDs are stable for retained slides.

integration/unified.css applies the shared design and vector color palette. integration/integrated.js loads unchanged source fragments, adds the common header, and fits technical content without cropping it. Original SVG figures are inlined for styling; no geometry or data is regenerated.

All 55 SensWear slides remain available: 36 in the main route and 19 as supplementary explanations/references. The sensor-kit photograph, campaign QR, app screenshots, and source credits are retained. Original source-file hashes are recorded in integration/original-file-hashes.json. Reveal.js 5.2.1 and KaTeX 0.16.22 licenses are included under vendor/.

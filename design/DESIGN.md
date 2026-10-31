---
name: TraceMind Design System
colors:
  surface: '#f8f9ff'
  surface-dim: '#cbdbf5'
  surface-bright: '#f8f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eff4ff'
  surface-container: '#e5eeff'
  surface-container-high: '#dce9ff'
  surface-container-highest: '#d3e4fe'
  on-surface: '#0b1c30'
  on-surface-variant: '#464555'
  inverse-surface: '#213145'
  inverse-on-surface: '#eaf1ff'
  outline: '#777587'
  outline-variant: '#c7c4d8'
  surface-tint: '#4d44e3'
  primary: '#3525cd'
  on-primary: '#ffffff'
  primary-container: '#4f46e5'
  on-primary-container: '#dad7ff'
  inverse-primary: '#c3c0ff'
  secondary: '#565e74'
  on-secondary: '#ffffff'
  secondary-container: '#dae2fd'
  on-secondary-container: '#5c647a'
  tertiary: '#003fac'
  on-tertiary: '#ffffff'
  tertiary-container: '#0555dd'
  on-tertiary-container: '#d1daff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#e2dfff'
  primary-fixed-dim: '#c3c0ff'
  on-primary-fixed: '#0f0069'
  on-primary-fixed-variant: '#3323cc'
  secondary-fixed: '#dae2fd'
  secondary-fixed-dim: '#bec6e0'
  on-secondary-fixed: '#131b2e'
  on-secondary-fixed-variant: '#3f465c'
  tertiary-fixed: '#dbe1ff'
  tertiary-fixed-dim: '#b4c5ff'
  on-tertiary-fixed: '#00174b'
  on-tertiary-fixed-variant: '#003ea8'
  background: '#f8f9ff'
  on-background: '#0b1c30'
  surface-variant: '#d3e4fe'
typography:
  display-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.02em
  display-lg-mobile:
    fontFamily: Inter
    fontSize: 26px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.015em
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.015em
  headline-sm:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.01em
  title-md:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: -0.005em
  body-default:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: 0em
  body-medium:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
    letterSpacing: 0em
  caption-ui:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.01em
  mono-metric-lg:
    fontFamily: JetBrains Mono
    fontSize: 24px
    fontWeight: '500'
    lineHeight: 28px
    letterSpacing: -0.02em
  mono-body:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: 0em
  mono-caption:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '400'
    lineHeight: 14px
    letterSpacing: 0em
  mono-badge:
    fontFamily: JetBrains Mono
    fontSize: 10px
    fontWeight: '500'
    lineHeight: 12px
    letterSpacing: 0.02em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-desktop: 1.5rem
  margin: 1rem
  margin-desktop: 1.5rem
  space-xxs: 0.125rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1rem
  space-xl: 1.5rem
  space-2xl: 2rem
---

## Brand & Style
The design system establishes a focused, high-clarity environment engineered for Site Reliability Engineers (SREs), infrastructure architects, and distributed systems developers. The system balances operational density with visual calm, avoiding superfluous decoration, heavy drop shadows, or simulated 3D effects.

The aesthetic fuses the disciplined minimalism of Linear and Vercel with the enterprise density and diagnostic legibility of Stripe Dashboard and Datadog. The visual posture is technical, surgical, and robust:
- **Atmosphere**: Crisp, controlled, high-contrast, and neutral. White working tiles emerge quietly over slate-tinted canvas substrates.
- **Tone**: Pragmatic, objective, precise, low-friction. 
- **Telemetry-First Ergonomics**: Maximum signal-to-noise ratio where telemetry metrics, distributed traces, and log payloads demand instant cognitive parsing during critical incidents.

## Colors
The color architecture relies on a disciplined light canvas with semantic-driven functional accents. Hue is employed strictly to encode system state, interactivity, and telemetry thresholds.

### Canvas & Structural Neutral Tiers
- **Canvas Base**: `#F8FAFC` (Slate 50) creates a calm, glare-free foundational backdrop.
- **Surface Elevation (Cards, Panels, Modals)**: `#FFFFFF` (Pure White).
- **Subtle Surface Secondary (Table headers, inactive rows, code blocks)**: `#F1F5F9` (Slate 100).
- **Structural Outlines & Separators**: `#E2E8F0` (Slate 200) for standard 1px container borders; `#CBD5E1` (Slate 300) for active or focused boundaries.

### Text & Glyph Hierarchy
- **Text Primary**: `#0F172A` (Slate 900) — high-contrast charcoal for core metrics, logs, and header labels.
- **Text Secondary**: `#475569` (Slate 600) — secondary descriptions, breadcrumbs, and muted table headers.
- **Text Muted / Tertiary**: `#64748B` (Slate 500) — timestamps, metadata tags, and inline unit descriptors.
- **Text Disabled**: `#94A3B8` (Slate 400).

### Semantic & Health Alert Palette
Health metrics must conform strictly to these deterministic tokens:
- **Healthy / Resolved**: `#10B981` (Emerald 500) with tint background `#ECFDF5` (Emerald 50) and stroke `#A7F3D0` (Emerald 200).
- **Warning / Degraded**: `#F59E0B` (Amber 500) with tint background `#FFFBEB` (Amber 50) and stroke `#FDE68A` (Amber 200).
- **Critical / Outage**: `#EF4444` (Red 500) with tint background `#FEF2F2` (Red 50) and stroke `#FECACA` (Red 200).
- **Informational / Discovery**: `#3B82F6` (Blue 500) with tint background `#EFF6FF` (Blue 50) and stroke `#BFDBFE` (Blue 200).

### Brand & Interactive Accent
- **Primary Indigo Accent**: `#4F46E5` (Indigo 600) for primary triggers, active selection rings, and trace highlights.
- **Primary Interactive Hover**: `#4338CA` (Indigo 700).
- **Subtle Indigo Surface Tint**: `#EEF2FF` (Indigo 50) for selected table rows and active navigation markers.

## Typography
The typography strategy enforces a split hierarchy: **Inter** handles structural UI labels, headings, and system interactions, while **JetBrains Mono** governs trace spans, span duration markers, hexadecimal hashes, IP addresses, log streams, and quantitative metrics.

### Sizing and Rhythms
- Base text scale is intentionally compact (13px standard body with 18px line height) to accommodate dense, analytical screen states without causing vertical fatigue.
- `font-feature-settings: "cv02", "cv03", "cv04", "cv11"` is recommended for Inter to reinforce disambiguated character geometry (e.g., distinguishing uppercase `I`, lowercase `l`, and digit `1`).
- Numerical values in cards, charts, and table rows must enforce tabular figures (`tnum`) to maintain visual vertical alignment across shifting values.

## Layout & Spacing
The layout model employs a fluid, multi-pane workbench layout designed for widescreen desktop observability workstations (1440px - 2560px), adapting down through compact laptops and mobile viewports.

### Multi-Pane Workbench Model
- **Collapsible Global Rail (Left)**: Fixed 56px (icon mode) or 240px (expanded tree view).
- **Context Drawer / Filter Aside**: 280px to 360px sticky sidebar for dynamic span filtering, facet search, and query construction.
- **Main Diagnostic Canvas**: Fluid grid dynamically calculating column structures based on active layout tiles:
  - Incident Command: 12-column layout.
  - Metrics Grid: 2-, 3-, or 4-column equalized card arrays.
  - Flamegraph & Trace Timeline: 1-column full-width viewport pane.

### Responsive Breakpoints
- **Mobile (< 768px)**: Single column reflow. Telemetry sidebars tuck into bottom sheets. Split flamegraph views transform to stacked sequential lists. Margin clamps to `1rem`.
- **Tablet / Small Laptop (768px - 1279px)**: 8-column layout. Drawers operate as slide-over overlays over the primary data table.
- **Desktop (>= 1280px)**: 12-column persistent multi-pane workbench with sticky context panels and persistent live-tail headers.

## Elevation & Depth
Depth is produced primarily through high-precision border definition, background tonal shifts, and micro-inset styling, bypassing blur-heavy skeuomorphism or ambient diffusion.

### Structural Depth Principles
- **No Heavy Drop Shadows**: Avoid diffuse Gaussian shadows. Ambient shadows introduce optical visual fuzz that degrades analytical table reading.
- **0.5px / 1px Micro Borders**: Surfaces use explicit `1px solid #E2E8F0` outlines to define clear bounding boxes against the `#F8FAFC` foundation.
- **Restrained Elevation Levels**:
  - **Level 0 (Canvas Base)**: `#F8FAFC` background.
  - **Level 1 (Card & Row Surface)**: `#FFFFFF` with `border: 1px solid #E2E8F0` and subtle inner rim `box-shadow: 0 1px 2px 0 rgba(15, 23, 42, 0.04)`.
  - **Level 2 (Popovers, Filter Menus, Tooltips)**: `#FFFFFF` with `border: 1px solid #CBD5E1`, `box-shadow: 0 4px 6px -1px rgba(15, 23, 42, 0.08), 0 2px 4px -2px rgba(15, 23, 42, 0.04)`.
  - **Level 3 (Diagnostic Modals, Hot-Key Command Palette)**: `#FFFFFF` surrounded by `1px solid #94A3B8`, with `box-shadow: 0 20px 25px -5px rgba(15, 23, 42, 0.1), 0 8px 10px -6px rgba(15, 23, 42, 0.05)`.
- **Hover & Active Affirmation**: Hovering over interactive card surfaces does not scale the object; it transitions the border color from `#E2E8F0` to `#CBD5E1` while reinforcing the micro-shadow.

## Shapes
The shape language implements a soft geometric profile (`roundedness: 1`). Radii stay tight, structured, and architectural to preserve screen density and respect grid alignment.

### Radius Assignments
- **Micro Radii (2px - 4px / `rounded-xs` to `rounded-sm`)**: Status indicator pills, code tokens, micro-badges, table cell tags, and scrollbar handles.
- **Component Radii (6px / `rounded`)**: Standard buttons, input elements, dropdown triggers, and select controls.
- **Container Radii (8px / `rounded-lg`)**: Metric summary cards, trace timeline viewports, log viewer terminals, and command palettes.
- **Modal / Popover Radii (10px - 12px / `rounded-xl`)**: Top-level modal sheets and flyout diagnostic inspect panels.
- **Circular (9999px / `rounded-full`)**: Strictly reserved for live ping SVG radar dots, user presence avatars, and toggle pill tracks.

## Components

### Buttons & Interactive Triggers
- **Primary Button**: Background `#4F46E5`, text `#FFFFFF`, border `1px solid transparent`, height `32px`, padding `0 12px`, typography `Inter 13px weight 500`. Hover: `#4338CA`. Active: `#3730A3`. Focus-visible: outline `2px solid #4F46E5` with `2px offset`.
- **Secondary / Neutral Button**: Background `#FFFFFF`, text `#0F172A`, border `1px solid #E2E8F0`, micro-shadow `0 1px 2px rgba(15, 23, 42, 0.04)`. Hover: background `#F8FAFC`, border `#CBD5E1`.
- **Ghost / Utility Action**: Background `transparent`, text `#64748B`, border `none`. Hover: background `#F1F5F9`, text `#0F172A`.

### Status Micro-Badges & Indicators
- **Indicator Composition**: Micro-badge components use a fixed height of `20px`, padding `0 6px`, border radius `4px`, and `JetBrains Mono 10px/weight 500`.
- **Variants**:
  - *Healthy*: Background `#ECFDF5`, text `#065F46`, border `1px solid #A7F3D0`. Includes a 6px solid `#10B981` SVG circular node.
  - *Warning*: Background `#FFFBEB`, text `#92400E`, border `1px solid #FDE68A`. Includes a 6px solid `#F59E0B` circular node.
  - *Critical*: Background `#FEF2F2`, text `#991B1B`, border `1px solid #FECACA`. Includes a 6px solid `#EF4444` circular node (with optional subtle CSS ping pulse for unacknowledged incidents).
  - *Neutral / Trace Info*: Background `#F1F5F9`, text `#334155`, border `1px solid #E2E8F0`.

### Data Tables (Dense Telemetry Grid)
- **Container**: White background, `1px solid #E2E8F0` border, `8px` border radius.
- **Header Row**: Height `32px`, background `#F8FAFC`, border-bottom `1px solid #E2E8F0`, typography `Inter 11px uppercase weight 600`, tracking `0.05em`, color `#64748B`.
- **Data Rows**: Height `36px` (compact mode) or `44px` (comfortable mode), alternating hover background `#F8FAFC`, selected row `#EEF2FF`. Border-bottom `1px solid #F1F5F9`.
- **Column Alignment**: Text aligned left; timestamps, durations, memory limits, and p99 metrics aligned right using `JetBrains Mono` tabular figures.

### Form Inputs & Query Terminals
- **Input Fields**: Height `32px`, background `#FFFFFF`, border `1px solid #CBD5E1`, border radius `6px`, text `Inter 13px #0F172A`, placeholder `#94A3B8`. Inner padding `0 10px`. Focus: border `#4F46E5`, ring `2px rgba(79, 70, 229, 0.15)`.
- **Query Filter Input (KQL / PromQL Style)**: Height `36px`, monospace input font `JetBrains Mono 12px`, with integrated prefix badge (e.g., `service:`, `cluster:`, `env:`) and clear action suffix.

### Metric KPI Cards
- **Structure**: Surface `#FFFFFF`, border `1px solid #E2E8F0`, radius `8px`, padding `12px 16px`.
- **Header**: Label `caption-ui` (`Inter 11px weight 500 #64748B`) paired with an auxiliary micro icon or sparkline.
- **Metric Value**: Numerical value using `mono-metric-lg` (`JetBrains Mono 24px weight 500 #0F172A`).
- **Delta Indicator**: Inline flex badge showing trend (e.g., `+12.4ms (+4.2%)`). Positive operational trend tinted `#10B981`, latency degradation or failure spike tinted `#EF4444`.

### Distributed Trace Gantt Bar
- **Track**: Height `18px`, background `#F1F5F9`, rounded `2px`.
- **Span Fill**: Color-coded by service taxonomy (e.g., Auth = `#6366F1`, Gateway = `#0EA5E9`, Database = `#F59E0B`, Third-Party = `#8B5CF6`). Error spans overlay `#EF4444` pattern hatch.
- **Span Text**: Overlaid inline `JetBrains Mono 10px weight 500` displaying service ID and duration (e.g., `redis.get: 1.42ms`).
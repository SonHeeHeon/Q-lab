<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# app/lib/presentation/heatmap/ — Market Heatmap

## Purpose
Real-time market sector heatmap — colour-coded tiles showing sector performance. Live data from the backend's heatmap API (cached, updated every 1 min). `session_badge.dart` shows market session status (장전/장중/장후).

## Key Files

| File | Description |
|------|-------------|
| `heatmap_screen.dart` | `HeatmapScreen` — grid of sector tiles, colour scale (red=up, blue=down KR convention) |
| `heatmap_controller.dart` | `heatmapProvider` (`FutureProvider<List<HeatmapSector>>`), auto-refresh timer |
| `session_badge.dart` | `SessionBadge` widget — shows 장전/장중/장후 based on KST time |

## For AI Agents

### Colour Convention (Korean Market)
- Red / positive change → rising
- Blue / negative change → falling  
(Opposite of Western convention)

### Refresh Cadence
Auto-refreshes every 60 seconds via `ref.invalidate(heatmapProvider)` in a periodic timer disposed with `ConsumerStatefulWidget.dispose`.

<!-- MANUAL: -->

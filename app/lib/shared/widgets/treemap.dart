/// File: app/lib/shared/widgets/treemap.dart
///
/// Squarified treemap layout + render widget. Pure-Dart, no external
/// packages. Used by the Market Heatmap screen and the embedded mini
/// heatmap on the Quant & AI Insights tab.
///
/// Algorithm: classic squarify (Bruls, Huijsen, van Wijk 2000) —
/// items are sorted by size desc, then packed in rows along the shorter
/// side of the remaining rect, finalizing a row whenever adding the next
/// item would worsen the worst-cell aspect ratio.
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';

class TreemapItem<T> {
  TreemapItem({required this.value, required this.size, required this.colorValue});

  /// Backing payload — typically a node DTO so the cell click handler
  /// can read code/name/etc.
  final T value;

  /// Cell area weight (must be > 0).
  final double size;

  /// Color intensity (e.g. percent change). Negative = blue/cool,
  /// positive = red/warm. Mapped to color via [colorForValue].
  final double colorValue;
}

class TreemapCell<T> {
  TreemapCell({required this.item, required this.rect});
  final TreemapItem<T> item;
  final Rect rect;
}

// ---------------------------------------------------------------------------
// Squarify algorithm
// ---------------------------------------------------------------------------

class Squarify {
  /// Lays out [items] inside [rect]. Items are NOT mutated; the result
  /// preserves order so the caller can map cell→item directly.
  static List<TreemapCell<T>> layout<T>(Rect rect, List<TreemapItem<T>> items) {
    if (items.isEmpty || rect.width <= 0 || rect.height <= 0) return const [];

    final filtered = items.where((it) => it.size > 0).toList()
      ..sort((a, b) => b.size.compareTo(a.size));
    if (filtered.isEmpty) return const [];

    final totalSize = filtered.fold<double>(0, (s, it) => s + it.size);
    final totalArea = rect.width * rect.height;
    final scale = totalArea / totalSize;
    final scaled = [
      for (final it in filtered)
        _ScaledItem<T>(item: it, area: it.size * scale),
    ];

    final result = <TreemapCell<T>>[];
    var remainingRect = rect;
    var remaining = scaled;

    while (remaining.isNotEmpty) {
      final shortSide = math.min(remainingRect.width, remainingRect.height);
      final row = <_ScaledItem<T>>[];
      var bestWorst = double.infinity;

      var i = 0;
      for (; i < remaining.length; i++) {
        row.add(remaining[i]);
        final worst = _worstAspect(row, shortSide);
        if (worst > bestWorst) {
          row.removeLast();
          break;
        }
        bestWorst = worst;
      }
      if (row.isEmpty) {
        // Should not happen unless remaining had zero-size items
        break;
      }

      _placeRow(row, remainingRect, result);
      remaining = remaining.sublist(row.length);
      remainingRect = _shrinkRect(remainingRect, row);
    }

    return result;
  }

  static double _worstAspect<T>(List<_ScaledItem<T>> row, double shortSide) {
    if (row.isEmpty) return double.infinity;
    final rowTotal = row.fold<double>(0, (s, it) => s + it.area);
    final w2 = shortSide * shortSide;
    var worst = 0.0;
    for (final it in row) {
      final ratio1 = (w2 * it.area) / (rowTotal * rowTotal);
      final ratio2 = (rowTotal * rowTotal) / (w2 * it.area);
      final r = math.max(ratio1, ratio2);
      if (r > worst) worst = r;
    }
    return worst;
  }

  static void _placeRow<T>(
    List<_ScaledItem<T>> row,
    Rect rect,
    List<TreemapCell<T>> out,
  ) {
    final rowTotal = row.fold<double>(0, (s, it) => s + it.area);
    if (rect.width >= rect.height) {
      // Row width along x = rowTotal / height; cells stack along y
      final rowWidth = rowTotal / rect.height;
      var y = rect.top;
      for (final it in row) {
        final h = it.area / rowWidth;
        out.add(TreemapCell(item: it.item, rect: Rect.fromLTWH(rect.left, y, rowWidth, h)));
        y += h;
      }
    } else {
      // Row height along y = rowTotal / width; cells stack along x
      final rowHeight = rowTotal / rect.width;
      var x = rect.left;
      for (final it in row) {
        final w = it.area / rowHeight;
        out.add(TreemapCell(item: it.item, rect: Rect.fromLTWH(x, rect.top, w, rowHeight)));
        x += w;
      }
    }
  }

  static Rect _shrinkRect<T>(Rect rect, List<_ScaledItem<T>> placedRow) {
    final rowTotal = placedRow.fold<double>(0, (s, it) => s + it.area);
    if (rect.width >= rect.height) {
      final consumed = rowTotal / rect.height;
      return Rect.fromLTWH(rect.left + consumed, rect.top, rect.width - consumed, rect.height);
    } else {
      final consumed = rowTotal / rect.width;
      return Rect.fromLTWH(rect.left, rect.top + consumed, rect.width, rect.height - consumed);
    }
  }
}

class _ScaledItem<T> {
  _ScaledItem({required this.item, required this.area});
  final TreemapItem<T> item;
  final double area;
}

// ---------------------------------------------------------------------------
// Color mapping (Korean convention: red = up, blue = down)
// ---------------------------------------------------------------------------

Color colorForChangePct(double pct, {double saturation = 4.0}) {
  // Normalize: ±[saturation]% maps to full intensity; clamp.
  final norm = (pct / saturation).clamp(-1.0, 1.0);
  if (norm.abs() < 0.05) {
    return const Color(0xFF52525B); // neutral zinc-600
  }
  if (norm > 0) {
    // Red ramp: light → deep red
    final t = norm; // 0..1
    return Color.lerp(const Color(0xFF7F1D1D), const Color(0xFFEF4444), t)!;
  } else {
    final t = -norm;
    return Color.lerp(const Color(0xFF1E3A8A), const Color(0xFF3B82F6), t)!;
  }
}

// ---------------------------------------------------------------------------
// Treemap widget
// ---------------------------------------------------------------------------

typedef TreemapCellTap<T> = void Function(T item);

class Treemap<T> extends StatelessWidget {
  const Treemap({
    super.key,
    required this.items,
    required this.labelBuilder,
    this.onCellTap,
    this.minLabelArea = 60 * 30.0,
    this.padding = 1.0,
  });

  final List<TreemapItem<T>> items;
  final String Function(T item) labelBuilder;
  final TreemapCellTap<T>? onCellTap;

  /// Hide labels when cell area < this (px²). Avoids unreadable text.
  final double minLabelArea;

  /// Gap between cells (px).
  final double padding;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final rect = Rect.fromLTWH(0, 0, constraints.maxWidth, constraints.maxHeight);
        final cells = Squarify.layout<T>(rect, items);
        return Stack(
          children: [
            for (final c in cells) _CellBox<T>(
              cell: c,
              label: labelBuilder(c.item.value),
              onTap: onCellTap,
              padding: padding,
              minLabelArea: minLabelArea,
            ),
          ],
        );
      },
    );
  }
}

class _CellBox<T> extends StatelessWidget {
  const _CellBox({
    required this.cell,
    required this.label,
    required this.onTap,
    required this.padding,
    required this.minLabelArea,
  });

  final TreemapCell<T> cell;
  final String label;
  final TreemapCellTap<T>? onTap;
  final double padding;
  final double minLabelArea;

  @override
  Widget build(BuildContext context) {
    final r = cell.rect;
    final color = colorForChangePct(cell.item.colorValue);
    final area = r.width * r.height;
    final showLabel = area >= minLabelArea && r.width > 36 && r.height > 22;

    final fontSize = math.max(9.0, math.min(13.0, math.sqrt(area) / 7));
    final pctText = '${cell.item.colorValue >= 0 ? '+' : ''}${cell.item.colorValue.toStringAsFixed(2)}%';

    final cell0 = GestureDetector(
      onTap: onTap == null ? null : () => onTap!(cell.item.value),
      child: Container(
        margin: EdgeInsets.all(padding / 2),
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.circular(2),
        ),
        padding: const EdgeInsets.all(4),
        alignment: Alignment.center,
        child: showLabel
            ? Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    label,
                    overflow: TextOverflow.ellipsis,
                    maxLines: 1,
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: fontSize,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  if (r.height > 40)
                    Text(
                      pctText,
                      style: TextStyle(
                        color: Colors.white.withValues(alpha: 0.9),
                        fontSize: fontSize - 1,
                      ),
                    ),
                ],
              )
            : const SizedBox.shrink(),
      ),
    );

    return Positioned(
      left: r.left,
      top: r.top,
      width: r.width,
      height: r.height,
      child: Tooltip(message: '$label  ($pctText)', child: cell0),
    );
  }
}

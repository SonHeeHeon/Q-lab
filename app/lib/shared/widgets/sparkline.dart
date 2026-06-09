/// File: app/lib/shared/widgets/sparkline.dart
///
/// Minimalist sparkline drawn with [CustomPaint]. Auto-scales to its
/// container, gradient fill, optional last-point dot, red/blue color
/// based on first→last direction (Korean market convention).
///
/// Until backend ships a price-history endpoint, [Sparkline.fromCodeDummy]
/// generates a deterministic random-walk seeded by the stock code so each
/// stock has a stable but distinct shape.
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';

class Sparkline extends StatelessWidget {
  const Sparkline({
    super.key,
    required this.values,
    this.color,
    this.fill = true,
    this.strokeWidth = 2.0,
    this.showLastDot = true,
  });

  final List<double> values;
  final Color? color;
  final bool fill;
  final double strokeWidth;
  final bool showLastDot;

  /// Dummy sparkline data seeded by [stockCode] so repeated renders
  /// produce the same shape. ~30 points random walk in [0..100].
  static List<double> fromCodeDummy(String stockCode, {int points = 30}) {
    var seed = 0;
    for (final r in stockCode.runes) {
      seed = (seed * 31 + r) & 0x7fffffff;
    }
    final rng = math.Random(seed);
    final out = <double>[];
    var v = 50.0 + rng.nextDouble() * 20;
    for (var i = 0; i < points; i++) {
      v += (rng.nextDouble() - 0.5) * 8;
      v = v.clamp(20, 80);
      out.add(v);
    }
    return out;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isUp = values.length >= 2 ? values.last >= values.first : true;
    final lineColor = color ?? (isUp ? Colors.redAccent : Colors.blueAccent);
    return CustomPaint(
      painter: _SparklinePainter(
        values: values,
        color: lineColor,
        fill: fill,
        strokeWidth: strokeWidth,
        showLastDot: showLastDot,
        baselineColor: theme.colorScheme.outlineVariant.withValues(alpha: 0.5),
      ),
      size: Size.infinite,
    );
  }
}

class _SparklinePainter extends CustomPainter {
  _SparklinePainter({
    required this.values,
    required this.color,
    required this.fill,
    required this.strokeWidth,
    required this.showLastDot,
    required this.baselineColor,
  });

  final List<double> values;
  final Color color;
  final bool fill;
  final double strokeWidth;
  final bool showLastDot;
  final Color baselineColor;

  @override
  void paint(Canvas canvas, Size size) {
    if (values.length < 2 || size.width <= 0 || size.height <= 0) return;
    final minV = values.reduce(math.min);
    final maxV = values.reduce(math.max);
    final range = (maxV - minV).abs() < 1e-9 ? 1.0 : (maxV - minV);

    Offset point(int i) {
      final x = (i / (values.length - 1)) * size.width;
      final y = size.height - ((values[i] - minV) / range) * size.height * 0.9 - size.height * 0.05;
      return Offset(x, y);
    }

    // Baseline (first value)
    final baselineY = size.height -
        ((values.first - minV) / range) * size.height * 0.9 -
        size.height * 0.05;
    canvas.drawLine(
      Offset(0, baselineY),
      Offset(size.width, baselineY),
      Paint()
        ..color = baselineColor
        ..strokeWidth = 1,
    );

    final path = Path()..moveTo(point(0).dx, point(0).dy);
    for (var i = 1; i < values.length; i++) {
      path.lineTo(point(i).dx, point(i).dy);
    }

    if (fill) {
      final fillPath = Path.from(path)
        ..lineTo(size.width, size.height)
        ..lineTo(0, size.height)
        ..close();
      canvas.drawPath(
        fillPath,
        Paint()
          ..shader = LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [color.withValues(alpha: 0.32), color.withValues(alpha: 0.02)],
          ).createShader(Offset.zero & size),
      );
    }

    canvas.drawPath(
      path,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = strokeWidth
        ..strokeJoin = StrokeJoin.round
        ..strokeCap = StrokeCap.round,
    );

    if (showLastDot) {
      final last = point(values.length - 1);
      canvas.drawCircle(last, strokeWidth + 1.6, Paint()..color = color);
      canvas.drawCircle(last, strokeWidth + 0.6, Paint()..color = Colors.white);
    }
  }

  @override
  bool shouldRepaint(covariant _SparklinePainter old) =>
      old.values != values || old.color != color || old.fill != fill;
}

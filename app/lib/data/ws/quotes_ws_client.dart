/// File: app/lib/data/ws/quotes_ws_client.dart
///
/// WebSocket client for `/ws/quotes`. Maintains a single shared connection
/// across all screens via [quotesProvider]. Exposes a `Map<code, Tick>`
/// state that screens watch with `.select((m) => m[code])` for per-row
/// rebuilds only when the relevant code's tick changes.
///
/// Outgoing wire format (PROJECT_BLUEPRINT.md §8.10):
///   { "action": "subscribe",   "codes": [...] }
///   { "action": "unsubscribe", "codes": [...] }
///
/// Incoming tick frame:
///   { "type": "tick", "code": "005930", "price": 75500,
///     "volume": 12345, "change_pct": 1.23, "timestamp": "..." }
///
/// Reconnect policy: exponential backoff (1s, 2s, 4s, ... capped at 30s).
/// On reconnect, all previously-subscribed codes are re-sent.
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:web_socket_channel/status.dart' as ws_status;

import '../../core/env.dart';

class Tick {
  Tick({
    required this.code,
    required this.price,
    required this.volume,
    required this.changePct,
    required this.timestamp,
  });

  final String code;
  final double price;
  final int volume;
  final double changePct;
  final DateTime timestamp;

  factory Tick.fromJson(Map<String, dynamic> j) => Tick(
        code: j['code'] as String,
        price: (j['price'] as num).toDouble(),
        volume: (j['volume'] as num?)?.toInt() ?? 0,
        changePct: (j['change_pct'] as num?)?.toDouble() ?? 0.0,
        timestamp: DateTime.parse(j['timestamp'] as String),
      );
}

class QuotesNotifier extends Notifier<Map<String, Tick>> {
  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _sub;
  final Set<String> _subscribed = {};
  int _reconnectAttempt = 0;
  Timer? _reconnectTimer;
  bool _disposed = false;

  // Listeners for alert_triggered frames (Alerts screen subscribes here).
  final _alertController = StreamController<int>.broadcast();
  Stream<int> get alertTriggeredStream => _alertController.stream;

  @override
  Map<String, Tick> build() {
    ref.onDispose(_dispose);
    _connect();
    return {};
  }

  // -- public API -------------------------------------------------------------

  void subscribe(Iterable<String> codes) {
    final fresh = codes.where((c) => !_subscribed.contains(c)).toList();
    _subscribed.addAll(codes);
    if (fresh.isNotEmpty) {
      _send({'action': 'subscribe', 'codes': fresh});
    }
  }

  void unsubscribe(Iterable<String> codes) {
    final drop = codes.where(_subscribed.contains).toList();
    _subscribed.removeAll(drop);
    if (drop.isNotEmpty) {
      _send({'action': 'unsubscribe', 'codes': drop});
    }
  }

  // -- internals --------------------------------------------------------------

  void _connect() {
    if (_disposed) return;
    final uri = Uri.parse('${Env.wsBaseUrl}/ws/quotes');
    try {
      _channel = WebSocketChannel.connect(uri);
      _sub = _channel!.stream.listen(
        _onMessage,
        onError: (Object e, StackTrace st) {
          debugPrint('[ws] error: $e');
          _scheduleReconnect();
        },
        onDone: () {
          debugPrint('[ws] closed (code=${_channel?.closeCode}); reconnecting');
          _scheduleReconnect();
        },
        cancelOnError: true,
      );
      _reconnectAttempt = 0;
      if (_subscribed.isNotEmpty) {
        _send({'action': 'subscribe', 'codes': _subscribed.toList()});
      }
    } catch (e) {
      debugPrint('[ws] connect failed: $e');
      _scheduleReconnect();
    }
  }

  void _onMessage(dynamic raw) {
    try {
      final text = raw is String ? raw : utf8.decode(raw as List<int>);
      final frame = jsonDecode(text);
      if (frame is! Map) return;
      final type = frame['type'];
      switch (type) {
        case 'tick':
          final tick = Tick.fromJson(frame.cast<String, dynamic>());
          state = {...state, tick.code: tick};
          break;
        case 'alert_triggered':
          final id = (frame['alert_id'] as num?)?.toInt();
          if (id != null) _alertController.add(id);
          break;
        default:
          break;
      }
    } catch (e) {
      debugPrint('[ws] parse error: $e raw=$raw');
    }
  }

  void _send(Map<String, dynamic> payload) {
    final ch = _channel;
    if (ch == null) return;
    try {
      ch.sink.add(jsonEncode(payload));
    } catch (e) {
      debugPrint('[ws] send failed: $e');
    }
  }

  void _scheduleReconnect() {
    if (_disposed) return;
    _sub?.cancel();
    _channel?.sink.close(ws_status.goingAway).catchError((_) {});
    _channel = null;

    final delaySeconds = (1 << _reconnectAttempt).clamp(1, 30);
    _reconnectAttempt = (_reconnectAttempt + 1).clamp(0, 5);
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(Duration(seconds: delaySeconds), _connect);
  }

  void _dispose() {
    _disposed = true;
    _reconnectTimer?.cancel();
    _sub?.cancel();
    _channel?.sink.close(ws_status.normalClosure).catchError((_) {});
    _alertController.close();
  }
}

final quotesProvider =
    NotifierProvider<QuotesNotifier, Map<String, Tick>>(QuotesNotifier.new);

/// Tiny convenience selector: per-code tick (rebuilds only when *this*
/// code's tick changes).
Tick? watchTick(Ref ref, String code) =>
    ref.watch(quotesProvider.select((m) => m[code]));

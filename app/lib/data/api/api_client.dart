/// File: app/lib/data/api/api_client.dart
///
/// Shared Dio HTTP client used by all per-resource API files.
/// Owns base URL, timeouts, logging, mock interceptor, and envelope unwrap.
///
/// Per-resource files (portfolio_api.dart etc.) NEVER instantiate Dio
/// themselves — they read this client through [dioProvider] so
/// interceptors apply uniformly.
library;

import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/env.dart';
import 'mock_interceptor.dart';

/// Safely coerce a JSON value (possibly `Map<dynamic, dynamic>` after
/// jsonDecode on Web) to the `Map<String, dynamic>` shape every
/// `fromJson` factory expects.
///
/// If the backend accidentally sends numeric keys (`{123: "x"}`), they
/// are coerced to strings — but a debug warning fires so developers
/// notice the contract violation instead of chasing silent lookup
/// failures downstream.
Map<String, dynamic> asJsonMap(Object? v) {
  if (v is Map<String, dynamic>) return v;
  if (v is Map) {
    assert(() {
      final nonString = v.keys.where((k) => k is! String).take(3).toList();
      if (nonString.isNotEmpty) {
        debugPrint(
          '[parse] asJsonMap got non-String keys (silently coerced): $nonString',
        );
      }
      return true;
    }());
    return v.map((k, val) => MapEntry(k.toString(), val));
  }
  throw FormatException('Expected JSON object, got ${v.runtimeType}');
}

/// Thrown by the envelope-unwrap interceptor when the backend
/// responds with `{ "error": { code, message, details } }`.
class ApiError implements Exception {
  ApiError({required this.code, required this.message, this.details, this.statusCode});

  final String code;
  final String message;
  final Map<String, dynamic>? details;
  final int? statusCode;

  @override
  String toString() => 'ApiError($code, $statusCode): $message';
}

final dioProvider = Provider<Dio>((ref) {
  final dio = Dio(
    BaseOptions(
      baseUrl: Env.apiBaseUrl,
      connectTimeout: const Duration(seconds: 8),
      receiveTimeout: const Duration(seconds: 12),
      responseType: ResponseType.json,
      headers: {'Content-Type': 'application/json'},
    ),
  );

  if (Env.useMock) {
    dio.interceptors.add(MockInterceptor());
  }

  dio.interceptors.add(_EnvelopeInterceptor());

  if (Env.isDev) {
    dio.interceptors.add(LogInterceptor(
      requestBody: true,
      responseBody: true,
      logPrint: (obj) => debugPrint(obj.toString()),
    ));
  }

  return dio;
});

/// Unwraps `{ "data": ..., "error": null|{...} }` envelopes:
///   - success → replaces `response.data` with the inner `data` payload
///   - error   → throws [ApiError]
class _EnvelopeInterceptor extends Interceptor {
  @override
  void onResponse(Response response, ResponseInterceptorHandler handler) {
    final body = response.data;
    if (body is Map && body.containsKey('data')) {
      final err = body['error'];
      if (err is Map) {
        throw ApiError(
          code: err['code']?.toString() ?? 'UNKNOWN',
          message: err['message']?.toString() ?? 'Unknown error',
          details: (err['details'] as Map?)?.cast<String, dynamic>(),
          statusCode: response.statusCode,
        );
      }
      response.data = body['data'];
    }
    handler.next(response);
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    final body = err.response?.data;
    if (body is Map && body['error'] is Map) {
      final e = body['error'] as Map;
      handler.reject(
        DioException(
          requestOptions: err.requestOptions,
          response: err.response,
          error: ApiError(
            code: e['code']?.toString() ?? 'UNKNOWN',
            message: e['message']?.toString() ?? 'Unknown error',
            details: (e['details'] as Map?)?.cast<String, dynamic>(),
            statusCode: err.response?.statusCode,
          ),
        ),
      );
      return;
    }
    handler.next(err);
  }
}

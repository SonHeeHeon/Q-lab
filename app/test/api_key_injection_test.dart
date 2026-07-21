/// Verifies the Dio client sends the in-app-configured backend API key as a
/// Bearer header, and honors the in-app base URL — the fix for "everything
/// 401s / DioException" when the backend has BACKEND_API_KEY set.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/core/preferences.dart';
import 'package:qlab/data/api/api_client.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Captures the final RequestOptions (after interceptors run) and returns a
/// valid envelope so the client's unwrap interceptor doesn't throw.
class _CaptureAdapter implements HttpClientAdapter {
  RequestOptions? captured;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    captured = options;
    return ResponseBody.fromString(
      jsonEncode({'data': null, 'error': null}),
      200,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

Future<ProviderContainer> _container(Map<String, Object> prefsValues) async {
  SharedPreferences.setMockInitialValues(prefsValues);
  final prefs = await SharedPreferences.getInstance();
  return ProviderContainer(
    overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
  );
}

void main() {
  test('injects the persisted API key as a Bearer header', () async {
    final container = await _container({'backend_api_key': 'secret-123'});
    final dio = container.read(dioProvider);
    final adapter = _CaptureAdapter();
    dio.httpClientAdapter = adapter;

    await dio.get('/api/ping');

    expect(adapter.captured!.headers['Authorization'], 'Bearer secret-123');
  });

  test('sends no Authorization header when no key is configured', () async {
    final container = await _container({});
    final dio = container.read(dioProvider);
    final adapter = _CaptureAdapter();
    dio.httpClientAdapter = adapter;

    await dio.get('/api/ping');

    expect(adapter.captured!.headers.containsKey('Authorization'), isFalse);
  });

  test('persisted base URL overrides the compile-time default', () async {
    final container =
        await _container({'backend_base_url': 'http://192.168.0.9:8000'});
    final dio = container.read(dioProvider);
    expect(dio.options.baseUrl, 'http://192.168.0.9:8000');
  });

  test('ApiKeyNotifier trims and clears', () async {
    final container = await _container({});
    await container.read(persistedApiKeyProvider.notifier).set('  abc  ');
    expect(container.read(persistedApiKeyProvider), 'abc');
    await container.read(persistedApiKeyProvider.notifier).set('');
    expect(container.read(persistedApiKeyProvider), '');
  });
}

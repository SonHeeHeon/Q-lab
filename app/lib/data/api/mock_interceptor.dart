/// File: app/lib/data/api/mock_interceptor.dart
///
/// Short-circuits outgoing requests with in-memory JSON fixtures when
/// `Env.useMock == true`.
///
/// CRITICAL Dio 5.x quirk:
///   `handler.resolve(response)` defaults to
///   `callFollowingResponseInterceptor = false` — meaning the
///   _EnvelopeInterceptor downstream NEVER runs for mocked requests.
///   So the mock MUST return the already-unwrapped inner data here.
///   For real backend traffic, the envelope interceptor unwraps the
///   `{data, error}` shell exactly the same way.
library;

import 'dart:async';

import 'package:dio/dio.dart';

import 'mock_fixtures.dart';

class MockInterceptor extends Interceptor {
  MockInterceptor({this.latency = const Duration(milliseconds: 150)});

  final Duration latency;

  @override
  Future<void> onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    final fixture = MockFixtures.resolve(options.method, options.path, options.queryParameters);
    if (fixture == null) {
      handler.next(options);
      return;
    }

    await Future<void>.delayed(latency);

    final response = Response<dynamic>(
      requestOptions: options,
      statusCode: fixture.statusCode,
      data: fixture.data, // ← already-unwrapped inner payload
    );
    handler.resolve(response);
  }
}

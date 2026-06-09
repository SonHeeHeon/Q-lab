/// File: app/lib/shared/widgets/stock_card.dart
///
/// Role:
///   Reusable compact card showing one stock (code, name, current
///   price, pct change, sparkline). Used across Home, Watchlist,
///   Portfolio, and Heatmap details.
///
/// Props (planned):
///   - stock: Stock
///   - position?: Position           // shows qty + unrealized P&L
///   - currentPrice?: Decimal        // live from WS feed
///   - onTap?: VoidCallback          // typically pushes /stock/:code
///
/// Connected modules:
///   - domain/entities/stock.dart, position.dart
///   - presentation/* (consumers)

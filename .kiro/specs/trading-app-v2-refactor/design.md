# Design Document

## Overview

The v2 architecture transforms the monolithic trading application into a clean, modular system following separation of concerns principles. The design maintains all existing functionality while organizing code into logical layers and components that are easier to maintain, test, and extend.

## Architecture

### High-Level Architecture

```
v2/
├── app.py                 # Main Flask application entry point
├── config/
│   ├── __init__.py
│   ├── settings.py        # Configuration management
│   └── config.json        # Configuration file
├── core/
│   ├── __init__.py
│   ├── trading_engine.py  # Core trading logic
│   ├── market_data.py     # Market data service
│   ├── auth.py           # Authentication service
│   └── alerts.py         # Alert management
├── data/
│   ├── __init__.py
│   ├── repositories.py    # Data access layer
│   └── models.py         # Data models
├── api/
│   ├── __init__.py
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── auth.py       # Authentication endpoints
│   │   ├── trading.py    # Trading endpoints
│   │   ├── market.py     # Market data endpoints
│   │   └── config.py     # Configuration endpoints
│   └── middleware.py     # Request/response middleware
├── utils/
│   ├── __init__.py
│   ├── helpers.py        # Utility functions
│   └── validators.py     # Input validation
├── static/               # Static assets (copied from original)
├── templates/            # HTML templates (copied from original)
└── requirements.txt      # Dependencies
```

### Layer Responsibilities

**API Layer (`api/`)**
- HTTP request/response handling
- Input validation and sanitization
- Error response formatting
- Route organization by feature

**Core Layer (`core/`)**
- Business logic implementation
- Trading algorithms and strategies
- Market data processing
- Authentication and authorization
- Alert management

**Data Layer (`data/`)**
- Data persistence and retrieval
- File operations (CSV, JSON)
- Data models and validation
- Repository pattern implementation

**Configuration Layer (`config/`)**
- Application settings management
- Environment-specific configurations
- Runtime configuration updates

**Utilities (`utils/`)**
- Shared helper functions
- Input validation utilities
- Common data transformations

## Components and Interfaces

### 1. Configuration Manager (`config/settings.py`)

**Purpose**: Centralized configuration management with validation and environment support.

**Key Methods**:
```python
class ConfigManager:
    def load_config(self, config_file: str) -> Dict
    def get(self, key: str, default=None) -> Any
    def set(self, key: str, value: Any) -> bool
    def validate_config(self) -> bool
    def save_config(self) -> bool
```

**Configuration Structure**:
```json
{
  "trading": {
    "ce_scrip_code": 874315,
    "pe_scrip_code": 874230,
    "quantity": 0,
    "capital": 100000,
    "stop_loss_percent": 5.0,
    "target_profit_percent": 10.0,
    "max_trades_per_day": 1000,
    "trading_start_time": "09:15",
    "trading_end_time": "23:30",
    "exchange": "B",
    "auto_scrip_update": "enabled",
    "price_difference_threshold": 40.0,
    "strategy_range": 8,
    "main_time_period": 300
  },
  "api": {
    "user_key": "Q4O7AsAK0iUABwjsvYfmfNU1cMiMWXai",
    "base_url": "https://api.stocko.in",
    "timeout": 30
  },
  "oauth": {
    "client_id": "SAS-CLIENT1",
    "client_secret": "...",
    "redirect_url": "http://127.0.0.1:65015/",
    "totp_secret": "T4JZGOUEE2G3NOCZ"
  }
}
```

### 2. Trading Engine (`core/trading_engine.py`)

**Purpose**: Core trading logic, strategy execution, and position management.

**Key Classes**:
```python
class TradingEngine:
    def __init__(self, config_manager, market_data_service, alert_manager)
    def start_trading(self) -> bool
    def stop_trading(self) -> bool
    def execute_strategy(self, market_data: Dict, scrip_type: str) -> None
    def open_position(self, side: str, price: float, scrip_type: str) -> bool
    def close_position(self, side: str, price: float, scrip_type: str) -> bool
    def square_off_all_positions(self) -> bool
    def calculate_qty(self, ltp: float, scrip_type: str) -> int
    def get_trading_stats(self, scrip_type: str) -> Dict

class PositionManager:
    def get_current_position(self, scrip_type: str) -> Optional[Dict]
    def update_position_stats(self, scrip_type: str, pnl: float) -> None
    def calculate_unrealized_pnl(self, scrip_type: str) -> float

class StrategyExecutor:
    def execute_early_session_strategy(self, market_info: Dict, scrip_type: str) -> None
    def execute_mid_session_strategy(self, market_info: Dict, scrip_type: str) -> None
    def execute_late_session_strategy(self, market_info: Dict, scrip_type: str) -> None
```

### 3. Market Data Service (`core/market_data.py`)

**Purpose**: External API integration, data fetching, and market data processing.

**Key Classes**:
```python
class MarketDataService:
    def __init__(self, config_manager, data_repository)
    def get_ltp(self, scrip_code: int) -> Optional[float]
    def get_index_ltp(self, scrip_code: int, exchange: str) -> Optional[Dict]
    def update_scrip_master(self) -> bool
    def find_nearest_scrips(self, target_ltp: float) -> Tuple[Dict, Dict]
    def get_real_market_data(self, scrip_type: str) -> Optional[Dict]

class ScripMasterManager:
    def load_scrip_master(self, file_path: str) -> bool
    def filter_scrip_data(self, instrument: str, ltp: float, exchange: str) -> List[Dict]
    def get_scrip_name(self, scrip_code: int) -> str

class PriceHistoryManager:
    def add_price(self, scrip_type: str, price: float) -> None
    def calculate_smma(self, data: List[float], period: int) -> Optional[float]
    def calculate_range_percent(self, scrip_type: str, period: int) -> float
    def adjust_history_for_scrip_change(self, old_ltp: float, new_ltp: float, scrip_type: str) -> None
```

### 4. Authentication Service (`core/auth.py`)

**Purpose**: OAuth2 flow, TOTP generation, and session management.

**Key Classes**:
```python
class AuthenticationService:
    def __init__(self, config_manager)
    def generate_totp(self) -> Optional[str]
    def get_access_token(self) -> Dict[str, Any]
    def refresh_access_token(self, auth_code: str) -> Dict[str, Any]
    def validate_credentials(self, username: str, password: str) -> bool
    def get_dynamic_password(self, name: str = "dhaval") -> str

class OAuth2Handler:
    def create_authorization_url(self) -> Tuple[str, str]
    def exchange_code_for_token(self, auth_code: str) -> Dict[str, Any]
    def save_token(self, token_data: Dict) -> bool
    def load_token(self) -> Optional[Dict]

class TOTPGenerator:
    def __init__(self, secret: str)
    def generate_current_code(self) -> str
    def verify_code(self, code: str) -> bool
```

### 5. Alert Manager (`core/alerts.py`)

**Purpose**: Alert creation, management, and delivery.

**Key Classes**:
```python
class AlertManager:
    def __init__(self, max_alerts: int = 100)
    def add_alert(self, alert_type: str, title: str, message: str, severity: str = 'info') -> None
    def get_alerts(self, limit: int = 10) -> List[Dict]
    def get_all_alerts(self) -> List[Dict]
    def mark_read(self, alert_id: int) -> bool
    def clear_old_alerts(self) -> None

class AlertFormatter:
    def format_trade_alert(self, trade_data: Dict) -> Dict
    def format_system_alert(self, message: str, severity: str) -> Dict
    def format_error_alert(self, error: Exception) -> Dict
```

### 6. Data Repository (`data/repositories.py`)

**Purpose**: Data persistence, file operations, and data access abstraction.

**Key Classes**:
```python
class OrderRepository:
    def save_order(self, order_data: Dict) -> bool
    def get_orders(self, scrip_type: Optional[str] = None) -> List[Dict]
    def get_order_history(self, filters: Dict) -> List[Dict]

class TradeRepository:
    def save_trade(self, trade_data: Dict) -> bool
    def get_trades(self, scrip_type: Optional[str] = None) -> List[Dict]
    def get_trade_statistics(self) -> Dict

class ConfigRepository:
    def load_config(self, file_path: str) -> Dict
    def save_config(self, config_data: Dict, file_path: str) -> bool

class ScripMasterRepository:
    def load_scrip_master(self, file_path: str) -> pd.DataFrame
    def save_scrip_master(self, data: List[Dict], file_path: str) -> bool
    def query_scrips(self, filters: Dict) -> List[Dict]
```

### 7. API Routes (`api/routes/`)

**Purpose**: HTTP endpoint organization by feature area.

**Route Organization**:
- `auth.py`: Login, logout, token management
- `trading.py`: Trading operations, positions, orders
- `market.py`: Market data, scrip information, LTP
- `config.py`: Configuration management, settings

## Data Models

### Core Data Models (`data/models.py`)

```python
@dataclass
class TradingConfig:
    ce_scrip_code: int
    pe_scrip_code: int
    quantity: int
    capital: float
    stop_loss_percent: float
    target_profit_percent: float
    # ... other fields

@dataclass
class Position:
    scrip_type: str
    side: str
    quantity: int
    entry_price: float
    current_price: float
    unrealized_pnl: float
    entry_time: datetime

@dataclass
class Order:
    timestamp: datetime
    side: str
    price: float
    quantity: int
    status: str
    scrip_type: str
    scrip_name: str

@dataclass
class Trade:
    entry_time: datetime
    exit_time: datetime
    side: str
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    scrip_type: str

@dataclass
class Alert:
    id: int
    type: str
    title: str
    message: str
    severity: str
    timestamp: datetime
    read: bool
```

## Error Handling

### Error Handling Strategy

1. **Service Layer Errors**: Each service catches and logs errors, returning structured error responses
2. **API Layer Errors**: HTTP-specific error handling with appropriate status codes
3. **Data Layer Errors**: File operation and data validation errors
4. **Trading Errors**: Order placement and market data errors with fallback mechanisms

### Error Response Format

```python
{
    "success": false,
    "error": {
        "code": "TRADING_ERROR",
        "message": "Failed to place order",
        "details": "Invalid scrip code provided"
    },
    "timestamp": "2024-01-01T12:00:00Z"
}
```

## Testing Strategy

The v2 architecture will support easier testing through:
- Dependency injection for service mocking
- Clear separation of concerns for isolated testing
- Modular components that can be tested independently
- Configuration-driven behavior for test environments

## Migration Strategy

### Phase 1: Core Services
1. Extract configuration management
2. Create trading engine service
3. Implement market data service
4. Set up data repositories

### Phase 2: API Refactoring
1. Organize routes by feature
2. Implement middleware
3. Add input validation
4. Update error handling

### Phase 3: Integration & Finalization
1. Wire services together
2. Update main application
3. Verify functionality
4. Performance optimization

### Backward Compatibility
- Maintain existing API contracts
- Preserve configuration file formats
- Keep same database/file structures
- Ensure identical frontend behavior
# 模拟交易系统公网部署方案

## 一、需求概述

### 1.1 核心需求
- **策略管理**：仅管理员（你）可提交和管理策略
- **用户系统**：用户自主注册、登录
- **订阅制**：策略级别付费，用户按需购买单个策略的查看权限
- **权限控制**：未付费用户只能看免费策略或预览，付费后才能查看完整数据

### 1.2 用户旅程
```
注册/登录 → 浏览策略市场 → 查看策略预览 → 购买订阅 → 查看完整策略数据
```

---

## 二、数据库设计

### 2.1 用户表 (users)
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT 1,
    is_admin BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 2.2 策略表 (strategies)
```sql
CREATE TABLE strategies (
    id VARCHAR(50) PRIMARY KEY,  -- 复用现有的 account_id
    name VARCHAR(100) NOT NULL,
    description TEXT,
    
    -- 定价相关
    price_monthly DECIMAL(10,2),  -- 月付价格，NULL表示不支持月付
    price_yearly DECIMAL(10,2),   -- 年付价格，NULL表示不支持年付
    is_public BOOLEAN DEFAULT 1,  -- 是否公开显示
    
    -- 回测相关（复用现有字段）
    initialize_code TEXT NOT NULL,
    handle_data_code TEXT NOT NULL,
    initial_cash DECIMAL(15,2) DEFAULT 100000,
    start_date VARCHAR(10) NOT NULL,
    asset_type VARCHAR(20) DEFAULT 'stock',
    benchmark VARCHAR(20) DEFAULT '000001.SH',
    status VARCHAR(20) DEFAULT 'running',  -- running/paused/stopped
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 2.3 订阅表 (subscriptions)
```sql
CREATE TABLE subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    strategy_id VARCHAR(50) NOT NULL,
    
    -- 订阅信息
    period_type VARCHAR(20) NOT NULL,  -- monthly/yearly
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    
    -- 状态
    status VARCHAR(20) DEFAULT 'active',  -- active/expired/cancelled
    
    -- 支付相关
    order_id VARCHAR(50) NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (strategy_id) REFERENCES strategies(id),
    UNIQUE(user_id, strategy_id)  -- 一个用户同一策略只能有一条活跃订阅
);
```

### 2.4 订单表 (orders)
```sql
CREATE TABLE orders (
    id VARCHAR(50) PRIMARY KEY,  -- 订单号：ORD{timestamp}{random}
    user_id INTEGER NOT NULL,
    strategy_id VARCHAR(50) NOT NULL,
    
    -- 订单信息
    period_type VARCHAR(20) NOT NULL,  -- monthly/yearly
    amount DECIMAL(10,2) NOT NULL,
    currency VARCHAR(10) DEFAULT 'CNY',
    
    -- 支付状态
    status VARCHAR(20) DEFAULT 'pending',  -- pending/paid/failed/refunded
    paid_at DATETIME,
    
    -- 第三方支付信息
    payment_channel VARCHAR(50),  -- wechat/alipay/stripe/custom
    payment_order_id VARCHAR(100),  -- 第三方订单号
    payment_data TEXT,  -- JSON存储完整的支付回调数据
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (strategy_id) REFERENCES strategies(id)
);
```

---

## 三、后端架构改造

### 3.1 目录结构调整
```
xxybacktest/
├── web/
│   ├── app.py                    # Flask应用入口
│   ├── config.py                 # 配置文件
│   ├── models/                   # 数据模型
│   │   ├── __init__.py
│   │   ├── user.py              # 用户模型
│   │   ├── strategy.py          # 策略模型
│   │   ├── subscription.py      # 订阅模型
│   │   └── order.py             # 订单模型
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── auth.py              # 登录/注册/登出
│   │   ├── public.py            # 公开页面（首页、策略列表）
│   │   ├── dashboard.py         # 用户仪表盘（已购策略）
│   │   ├── strategy.py          # 策略详情（权限控制）
│   │   ├── api.py               # API接口
│   │   ├── payment.py           # 支付相关
│   │   └── admin.py             # 管理员接口（策略管理）
│   ├── templates/
│   │   ├── base.html
│   │   ├── index.html           # 首页
│   │   ├── auth/
│   │   │   ├── login.html
│   │   │   └── register.html
│   │   ├── strategies/
│   │   │   ├── list.html        # 策略列表
│   │   │   └── detail.html      # 策略详情
│   │   ├── user/
│   │   │   └── dashboard.html   # 用户中心
│   │   └── payment/
│   │       └── checkout.html    # 支付页面
│   ├── static/
│   │   ├── css/
│   │   └── js/
│   └── utils/
│       ├── __init__.py
│       ├── auth.py              # 认证工具
│       ├── decorators.py        # 权限装饰器
│       └── payment.py           # 支付工具基类
└── simulation/                   # 现有模拟交易系统
```

### 3.2 核心代码实现

#### 3.2.1 用户模型 (web/models/user.py)
```python
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

class User(UserMixin):
    def __init__(self, id=None, username=None, email=None, 
                 password_hash=None, is_active=True, is_admin=False):
        self.id = id
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.is_active = is_active
        self.is_admin = is_admin
        self.created_at = datetime.now()
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    @staticmethod
    def get_by_id(user_id):
        # 从SQLite查询
        pass
    
    @staticmethod
    def get_by_email(email):
        pass
    
    def save(self):
        pass
```

#### 3.2.2 权限装饰器 (web/utils/decorators.py)
```python
from functools import wraps
from flask import abort, current_user
from flask_login import login_required

def require_subscription(strategy_id_param='strategy_id'):
    """检查用户是否订阅了指定策略"""
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            strategy_id = kwargs.get(strategy_id_param)
            if not strategy_id:
                abort(400)
            
            # 管理员直接放行
            if current_user.is_admin:
                return f(*args, **kwargs)
            
            # 检查是否订阅
            from ..models.subscription import Subscription
            sub = Subscription.get_active(current_user.id, strategy_id)
            if not sub:
                # 未订阅，返回预览模式或重定向到购买页
                return abort(403)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def admin_required(f):
    """仅管理员可访问"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function
```

#### 3.2.3 支付接口基类 (web/utils/payment.py)
```python
from abc import ABC, abstractmethod

class PaymentProvider(ABC):
    """支付提供商抽象基类，实现你自己的支付渠道"""
    
    @abstractmethod
    def create_order(self, order_id, amount, description, **kwargs):
        """
        创建支付订单
        返回: {
            'success': True/False,
            'pay_url': '...',  # 跳转支付的URL
            'pay_data': {...},  # 小程序/H5需要的参数
            'provider_order_id': '...'  # 第三方订单号
        }
        """
        pass
    
    @abstractmethod
    def verify_callback(self, request_data):
        """
        验证支付回调
        返回: {
            'valid': True/False,
            'order_id': '...',  # 你的订单号
            'provider_order_id': '...',
            'paid_amount': ...,
            'paid_at': datetime
        }
        """
        pass
    
    @abstractmethod
    def query_order(self, provider_order_id):
        """查询订单状态"""
        pass

# 示例：实现你自己的支付渠道
class MyPaymentProvider(PaymentProvider):
    def create_order(self, order_id, amount, description, **kwargs):
        # 调用你的支付渠道API创建订单
        # 返回支付URL或支付参数
        pass
    
    def verify_callback(self, request_data):
        # 验证支付回调签名
        # 返回验证结果
        pass
    
    def query_order(self, provider_order_id):
        pass
```

#### 3.2.4 策略详情路由 (web/routes/strategy.py)
```python
from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user
from ..utils.decorators import require_subscription
from ...simulation.db_utils import get_account_db

strategy_bp = Blueprint('strategy', __name__, url_prefix='/strategy')

@strategy_bp.route('/<strategy_id>')
def detail(strategy_id):
    """策略详情页 - 所有人可访问，但展示内容不同"""
    # 获取策略信息
    strategy = get_strategy_by_id(strategy_id)
    if not strategy or not strategy.is_public:
        abort(404)
    
    # 检查用户订阅状态
    has_access = False
    preview_days = 7  # 未订阅用户只能看最近7天
    
    if current_user.is_authenticated:
        if current_user.is_admin:
            has_access = True
        else:
            from ..models.subscription import Subscription
            sub = Subscription.get_active(current_user.id, strategy_id)
            has_access = sub is not None
    
    # 获取策略数据
    nav_data = get_strategy_nav(strategy_id, 
                                full_access=has_access, 
                                preview_days=preview_days)
    indicators = get_strategy_indicators(strategy_id) if has_access else None
    
    return render_template('strategies/detail.html',
                         strategy=strategy,
                         has_access=has_access,
                         nav_data=nav_data,
                         indicators=indicators)

@strategy_bp.route('/<strategy_id>/positions')
@require_subscription('strategy_id')
def positions(strategy_id):
    """持仓数据 - 需要订阅"""
    # 返回持仓数据
    pass

@strategy_bp.route('/<strategy_id>/orders')
@require_subscription('strategy_id')
def orders(strategy_id):
    """订单数据 - 需要订阅"""
    pass
```

---

## 四、前端页面设计

### 4.1 策略列表页 (/strategies)
```html
<!-- 展示所有公开策略 -->
<div class="strategy-grid">
  {% for strategy in strategies %}
  <div class="strategy-card">
    <h3>{{ strategy.name }}</h3>
    <p>{{ strategy.description }}</p>
    <div class="strategy-stats">
      <span>累计收益: {{ strategy.total_return }}%</span>
      <span>最大回撤: {{ strategy.max_drawdown }}%</span>
    </div>
    <div class="strategy-price">
      {% if strategy.price_monthly %}
        <span>¥{{ strategy.price_monthly }}/月</span>
      {% endif %}
    </div>
    <a href="/strategy/{{ strategy.id }}">查看详情</a>
  </div>
  {% endfor %}
</div>
```

### 4.2 策略详情页 (/strategy/<id>)
```html
<!-- 顶部：策略基本信息 -->
<div class="strategy-header">
  <h1>{{ strategy.name }}</h1>
  <p>{{ strategy.description }}</p>
</div>

<!-- 中间：收益曲线 -->
<div class="nav-chart">
  <!-- ECharts 展示净值曲线 -->
  <!-- 未订阅用户只显示最近7天，且提示"订阅查看完整数据" -->
</div>

<!-- 底部：根据权限显示 -->
{% if has_access %}
  <div class="full-data">
    <h2>绩效指标</h2>
    <!-- 夏普比率、最大回撤等 -->
    
    <h2>当前持仓</h2>
    <!-- 持仓表格 -->
    
    <h2>历史成交</h2>
    <!-- 订单列表 -->
  </div>
{% else %}
  <div class="subscribe-cta">
    <p>订阅后可查看完整历史数据、持仓详情和实时更新</p>
    <div class="price-options">
      {% if strategy.price_monthly %}
      <a href="/payment/checkout?strategy_id={{ strategy.id }}&period=monthly">
        月付 ¥{{ strategy.price_monthly }}
      </a>
      {% endif %}
      {% if strategy.price_yearly %}
      <a href="/payment/checkout?strategy_id={{ strategy.id }}&period=yearly">
        年付 ¥{{ strategy.price_yearly }}
        <span>省 {{ calculate_discount(strategy) }}%</span>
      </a>
      {% endif %}
    </div>
  </div>
{% endif %}
```

### 4.3 用户中心 (/dashboard)
```html
<!-- 已购策略 -->
<h2>我的订阅</h2>
<div class="subscription-list">
  {% for sub in subscriptions %}
  <div class="subscription-card">
    <h3>{{ sub.strategy_name }}</h3>
    <p>到期时间: {{ sub.end_date }}</p>
    <a href="/strategy/{{ sub.strategy_id }}">查看策略</a>
    <a href="/payment/checkout?strategy_id={{ sub.strategy_id }}&renew=1">
      续费
    </a>
  </div>
  {% endfor %}
</div>

<!-- 订单历史 -->
<h2>订单记录</h2>
<table>
  <tr><th>订单号</th><th>策略</th><th>金额</th><th>状态</th><th>时间</th></tr>
  {% for order in orders %}
  <tr>
    <td>{{ order.id }}</td>
    <td>{{ order.strategy_name }}</td>
    <td>¥{{ order.amount }}</td>
    <td>{{ order.status }}</td>
    <td>{{ order.created_at }}</td>
  </tr>
  {% endfor %}
</table>
```

---

## 五、支付流程实现

### 5.1 创建订单流程
```
用户点击购买 → 创建订单(orders表) → 调用支付渠道 → 返回支付页 → 用户完成支付
```

```python
@payment_bp.route('/checkout')
@login_required
def checkout():
    strategy_id = request.args.get('strategy_id')
    period_type = request.args.get('period')  # monthly/yearly
    
    strategy = get_strategy_by_id(strategy_id)
    amount = strategy.price_monthly if period_type == 'monthly' else strategy.price_yearly
    
    # 创建订单
    order_id = generate_order_id()
    order = Order(
        id=order_id,
        user_id=current_user.id,
        strategy_id=strategy_id,
        period_type=period_type,
        amount=amount
    )
    order.save()
    
    # 调用支付渠道
    provider = get_payment_provider()
    result = provider.create_order(
        order_id=order_id,
        amount=amount,
        description=f"{strategy.name} {period_type}订阅"
    )
    
    if result['success']:
        # 保存第三方订单号
        order.payment_order_id = result['provider_order_id']
        order.payment_channel = 'your_channel'
        order.save()
        
        # 跳转到支付页面
        return redirect(result['pay_url'])
    else:
        flash('创建支付订单失败')
        return redirect('/strategies')
```

### 5.2 支付回调处理
```python
@payment_bp.route('/callback', methods=['POST'])
def payment_callback():
    """支付渠道回调接口"""
    # 验证回调签名
    provider = get_payment_provider()
    result = provider.verify_callback(request.get_data())
    
    if not result['valid']:
        return 'FAIL', 400
    
    # 更新订单状态
    order = Order.get_by_id(result['order_id'])
    if not order:
        return 'ORDER_NOT_FOUND', 404
    
    if order.status == 'pending':
        order.status = 'paid'
        order.paid_at = result['paid_at']
        order.save()
        
        # 创建/更新订阅
        from ..models.subscription import Subscription
        Subscription.create_or_extend(
            user_id=order.user_id,
            strategy_id=order.strategy_id,
            period_type=order.period_type,
            order_id=order.id
        )
    
    return 'SUCCESS'
```

### 5.3 支付状态主动查询（补偿机制）
```python
# 定时任务：每小时查询待支付订单状态
# 防止回调丢失导致订单卡死

def check_pending_orders():
    """检查待支付订单"""
    pending_orders = Order.get_pending(timeout_minutes=30)
    provider = get_payment_provider()
    
    for order in pending_orders:
        result = provider.query_order(order.payment_order_id)
        if result['status'] == 'paid':
            # 手动触发支付成功处理
            process_payment_success(order, result)
```

---

## 六、管理员后台

### 6.1 策略管理 (/admin/strategies)
```python
@admin_bp.route('/strategies')
@admin_required
def strategy_list():
    """所有策略列表"""
    strategies = Strategy.get_all()
    return render_template('admin/strategies.html', strategies=strategies)

@admin_bp.route('/strategies/new', methods=['GET', 'POST'])
@admin_required
def create_strategy():
    """新建策略"""
    if request.method == 'POST':
        # 从表单获取数据
        strategy = Strategy(
            id=f"strat_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            name=request.form['name'],
            description=request.form['description'],
            price_monthly=request.form.get('price_monthly', type=float),
            price_yearly=request.form.get('price_yearly', type=float),
            initialize_code=request.form['initialize_code'],
            handle_data_code=request.form['handle_data_code'],
            start_date=request.form['start_date'],
            initial_cash=request.form.get('initial_cash', 100000, type=float)
        )
        strategy.save()
        
        # 立即跑一次回测生成初始数据
        from ...simulation.runner import run_single
        run_single(strategy.id, end_date=today())
        
        flash('策略创建成功')
        return redirect('/admin/strategies')
    
    return render_template('admin/create_strategy.html')

@admin_bp.route('/strategies/<strategy_id>/toggle', methods=['POST'])
@admin_required
def toggle_strategy(strategy_id):
    """上下架策略"""
    strategy = Strategy.get_by_id(strategy_id)
    strategy.is_public = not strategy.is_public
    strategy.save()
    return redirect('/admin/strategies')
```

### 6.2 用户管理 (/admin/users)
```python
@admin_bp.route('/users')
@admin_required
def user_list():
    users = User.get_all()
    return render_template('admin/users.html', users=users)

@admin_bp.route('/users/<user_id>/grant', methods=['POST'])
@admin_required
def grant_subscription(user_id):
    """手动赠送订阅（用于推广或客服补偿）"""
    strategy_id = request.form['strategy_id']
    days = request.form.get('days', 30, type=int)
    
    # 创建免费订阅记录
    Subscription.grant_trial(user_id, strategy_id, days)
    flash(f'已赠送 {days} 天订阅')
    return redirect(f'/admin/users/{user_id}')
```

---

## 七、部署配置

### 7.1 配置文件 (web/config.py)
```python
import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # 数据库
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///app.db'
    
    # 模拟交易数据路径
    XXYDB_PATH = os.environ.get('XXYDB_PATH') or './data'
    
    # 支付配置
    PAYMENT_CHANNEL = os.environ.get('PAYMENT_CHANNEL') or 'custom'
    PAYMENT_API_KEY = os.environ.get('PAYMENT_API_KEY')
    PAYMENT_API_SECRET = os.environ.get('PAYMENT_API_SECRET')
    PAYMENT_CALLBACK_URL = os.environ.get('PAYMENT_CALLBACK_URL') or '/payment/callback'
    
    # 管理员账号
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL') or 'admin@example.com'

class ProductionConfig(Config):
    DEBUG = False
    # 生产环境使用更安全的配置
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
```

### 7.2 Docker 部署
```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install -r requirements.txt

# 复制代码
COPY . .

# 创建数据目录
RUN mkdir -p /app/data/simulation_results

# 环境变量
ENV FLASK_APP=xxybacktest.web.app
ENV PYTHONPATH=/app
ENV XXYDB_PATH=/app/data

EXPOSE 5000

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "xxybacktest.web.app:create_app()"]
```

```yaml
# docker-compose.yml
version: '3'
services:
  web:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
      - ./app.db:/app/app.db
    environment:
      - SECRET_KEY=your-secret-key
      - PAYMENT_API_KEY=your-payment-key
      - ADMIN_EMAIL=your-admin@email.com
    restart: always

  # 定时任务容器（运行Plombery每日回测）
  scheduler:
    build: .
    command: python run_simulation.py
    volumes:
      - ./data:/app/data
      - ./app.db:/app/app.db
    restart: always
```

### 7.3 Nginx 配置
```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    # 强制HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    # 静态文件
    location /static {
        alias /app/xxybacktest/web/static;
        expires 30d;
    }
    
    # 反向代理到Flask
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # 支付回调路径（增加超时时间）
    location /payment/callback {
        proxy_pass http://127.0.0.1:5000;
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
    }
}
```

---

## 八、实施时间表

| 阶段 | 内容 | 预计时间 |
|------|------|---------|
| **第1周** | | |
| Day 1-2 | 数据库表创建、用户模型、登录注册 | 2天 |
| Day 3-4 | 策略模型改造、策略列表/详情页 | 2天 |
| Day 5 | 权限装饰器、订阅检查逻辑 | 1天 |
| **第2周** | | |
| Day 1-3 | 支付接口基类、订单系统、回调处理 | 3天 |
| Day 4-5 | 用户中心页面、订阅管理 | 2天 |
| **第3周** | | |
| Day 1-2 | 管理员后台（策略CRUD） | 2天 |
| Day 3-4 | 前端页面美化、响应式适配 | 2天 |
| Day 5 | 部署测试、Nginx配置、SSL | 1天 |
| **第4周** | | |
| Day 1-3 | 缓冲时间（处理意外问题） | 3天 |
| Day 4-5 | 内测、修复Bug、上线 | 2天 |

**总计：约 3-4 周**

---

## 九、关键检查清单

### 上线前必须完成
- [ ] 用户注册/登录/登出正常
- [ ] 密码加密存储
- [ ] 策略列表正确展示
- [ ] 未登录用户只能看免费内容
- [ ] 支付流程端到端测试通过
- [ ] 支付回调正确处理
- [ ] 订阅到期后自动失效
- [ ] 管理员能创建/编辑策略
- [ ] HTTPS证书配置正确
- [ ] 数据库定期备份
- [ ] 支付密钥不在代码中硬编码
- [ ] 错误日志记录

### 安全事项
- [ ] SQL注入防护（使用参数化查询）
- [ ] XSS防护（模板自动转义）
- [ ] CSRF保护（Flask-WTF）
- [ ] 支付回调签名验证
- [ ] 敏感操作需要登录
- [ ] 密码强度检查

---

## 十、常见问题

### Q1: 现有模拟交易数据如何迁移？
```python
# 写个迁移脚本，把现有 account_id 迁移到 strategies 表
# 标记为免费或设置价格

def migrate_accounts():
    db = get_db()
    accounts = db.read('simulation_accounts')
    
    for account in accounts:
        strategy = Strategy(
            id=account['account_id'],
            name=account.get('name', '未命名策略'),
            initialize_code=account['initialize_code'],
            handle_data_code=account['handle_data_code'],
            initial_cash=account['initial_cash'],
            start_date=account['start_date'],
            # 默认免费，后续在后台修改价格
            price_monthly=None,
            price_yearly=None,
            is_public=True
        )
        strategy.save()
```

### Q2: 如何支持促销码/折扣？
在订单表中增加 `promo_code` 字段，创建订单时验证折扣码并计算实际金额。

### Q3: 如何处理用户退款？
- 在管理员后台添加退款按钮
- 调用支付渠道的退款接口
- 订阅按比例延长或标记为refunded

### Q4: 如何防止用户分享账号？
- 限制同时登录设备数（记录session）
- 异地登录提醒
- 异常访问频率限制

---

## 附录：参考代码片段

### A. 数据库初始化脚本
```python
# init_db.py
import sqlite3

def init_db():
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    # 创建所有表
    cursor.executescript('''
    -- 粘贴上面的建表SQL
    ''')
    
    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
```

### B. 环境变量模板
```bash
# .env
SECRET_KEY=your-super-secret-key-here
DATABASE_URL=sqlite:///app.db
XXYDB_PATH=./data

# 支付配置
PAYMENT_CHANNEL=custom
PAYMENT_API_KEY=your-api-key
PAYMENT_API_SECRET=your-api-secret
PAYMENT_CALLBACK_URL=https://your-domain.com/payment/callback

# 管理员
ADMIN_EMAIL=admin@your-domain.com
ADMIN_PASSWORD=your-admin-password
```

### C. 启动脚本
```bash
#!/bin/bash
# start.sh

export $(cat .env | xargs)

cd /app

# 初始化数据库（如果不存在）
python init_db.py

# 创建管理员账号
python -c "
from xxybacktest.web.models.user import User
admin = User(
    username='admin',
    email='$ADMIN_EMAIL',
    is_admin=True
)
admin.set_password('$ADMIN_PASSWORD')
admin.save()
"

# 启动服务
gunicorn -w 4 -b 0.0.0.0:5000 xxybacktest.web.app:create_app()
```

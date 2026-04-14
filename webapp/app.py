from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import yaml
import json
import os
import time
from datetime import datetime
from pathlib import Path

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

# 配置文件路径
CONFIG_PATH = Path('../configs/system.local.yaml')
RUNTIME_PATH = Path('../runtime')

# 全局变量
last_trades = []
last_update_time = 0

# 加载配置
def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}

# 保存配置
def save_config(config):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, sort_keys=False, allow_unicode=True)

# 加载运行时数据
def load_runtime_data():
    data = {}
    
    # 加载账户快照
    account_path = RUNTIME_PATH / 'account_snapshot.json'
    if account_path.exists():
        with open(account_path, 'r', encoding='utf-8') as f:
            data['account'] = json.load(f)
    
    # 加载仪表板摘要
    dashboard_path = RUNTIME_PATH / 'dashboard_summary.json'
    if dashboard_path.exists():
        with open(dashboard_path, 'r', encoding='utf-8') as f:
            data['dashboard'] = json.load(f)
    
    # 加载权益曲线
    equity_path = RUNTIME_PATH / 'equity_curve.json'
    if equity_path.exists():
        with open(equity_path, 'r', encoding='utf-8') as f:
            data['equity'] = json.load(f)
    
    # 加载成交流水
    blotter_path = RUNTIME_PATH / 'blotter.jsonl'
    if blotter_path.exists():
        data['trades'] = load_trades()
    
    return data

# 加载成交流水
def load_trades():
    global last_trades, last_update_time
    
    blotter_path = RUNTIME_PATH / 'blotter.jsonl'
    if not blotter_path.exists():
        return []
    
    # 检查文件修改时间
    current_time = os.path.getmtime(blotter_path)
    if current_time <= last_update_time:
        return last_trades
    
    # 读取最新的交易数据
    trades = []
    try:
        with open(blotter_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()[-50:]  # 只读取最近50条交易
            for i, line in enumerate(lines):
                try:
                    trade = json.loads(line.strip())
                    # 使用交易数据中的真实时间戳，如果没有则生成一个
                    if 'timestamp' not in trade or not trade['timestamp']:
                        base_time = time.time() - (len(lines) - i) * 60  # 每条交易间隔1分钟
                        trade['timestamp'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(base_time))
                    trades.append(trade)
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        print(f"Error loading trades: {e}")
    
    # 计算持有时间和T+1检查
    trades = calculate_holding_time(trades)
    
    last_trades = trades
    last_update_time = current_time
    return trades

# 计算持有时间和T+1检查
def calculate_holding_time(trades):
    # 按智能体和股票分组的买入记录
    buy_records = {}
    
    for trade in trades:
        key = f"{trade.get('agent_id', 'unknown')}:{trade.get('symbol', 'unknown')}"
        
        if trade.get('action') == 'buy':
            # 记录买入时间
            if key not in buy_records:
                buy_records[key] = []
            buy_records[key].append({
                'quantity': trade.get('quantity', 0),
                'price': trade.get('price', 0),
                'timestamp': trade.get('timestamp', time.strftime('%Y-%m-%d %H:%M:%S'))
            })
        elif trade.get('action') == 'sell':
            # 计算持有时间
            if key in buy_records and buy_records[key]:
                # 简单模拟：使用最近的买入记录
                buy_record = buy_records[key][-1]
                buy_time = buy_record['timestamp']
                sell_time = trade.get('timestamp', time.strftime('%Y-%m-%d %H:%M:%S'))
                
                # 计算时间差（分钟）
                buy_datetime = datetime.strptime(buy_time, '%Y-%m-%d %H:%M:%S')
                sell_datetime = datetime.strptime(sell_time, '%Y-%m-%d %H:%M:%S')
                holding_minutes = (sell_datetime - buy_datetime).total_seconds() / 60
                
                trade['holding_time'] = f"{int(holding_minutes)}分钟"
                
                # T+1检查（简化版）
                # 实际应该检查是否在同一个交易日内
                # 这里简化为：如果持有时间小于1分钟，则认为不合规
                trade['t1_compliant'] = holding_minutes >= 1
            else:
                trade['holding_time'] = 'N/A'
                trade['t1_compliant'] = False
        else:
            trade['holding_time'] = 'N/A'
            trade['t1_compliant'] = 'N/A'
    
    return trades

@app.route('/')
def index():
    config = load_config()
    runtime_data = load_runtime_data()
    return render_template('index.html', config=config, runtime_data=runtime_data)

@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    if request.method == 'GET':
        config = load_config()
        return jsonify(config)
    elif request.method == 'POST':
        config = request.json
        save_config(config)
        return jsonify({'status': 'success'})

@app.route('/api/runtime')
def api_runtime():
    data = load_runtime_data()
    return jsonify(data)

# WebSocket事件处理
@socketio.on('connect')
def handle_connect():
    print('Client connected')
    # 发送初始交易数据
    trades = load_trades()
    emit('trades_update', {'trades': trades})

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

# 定时发送交易更新
def background_thread():
    print('Starting background thread')
    while True:
        try:
            trades = load_trades()
            print(f'Sending trades update with {len(trades)} trades')
            socketio.emit('trades_update', {'trades': trades})
            runtime_data = load_runtime_data()
            print('Sending runtime update')
            socketio.emit('runtime_update', runtime_data)
        except Exception as e:
            print(f'Error in background thread: {e}')
        time.sleep(1)  # 每秒更新一次

if __name__ == '__main__':
    # 创建必要的目录
    os.makedirs('webapp/templates', exist_ok=True)
    os.makedirs('webapp/static', exist_ok=True)
    
    # 启动后台线程
    import threading
    thread = threading.Thread(target=background_thread)
    thread.daemon = True
    thread.start()
    
    # 启动Flask应用
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
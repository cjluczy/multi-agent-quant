from __future__ import annotations

import math
from typing import Dict, List, Optional

from ..data_layer.feeds import Tick


class FactorCalculator:
    def __init__(self):
        self.price_history: Dict[str, List[float]] = {}
        self.volume_history: Dict[str, List[float]] = {}
        self.window_size = 20

    def update(self, tick: Tick):
        """更新价格和成交量历史"""
        if tick.symbol not in self.price_history:
            self.price_history[tick.symbol] = []
            self.volume_history[tick.symbol] = []
        
        self.price_history[tick.symbol].append(tick.price)
        self.volume_history[tick.symbol].append(tick.volume)
        
        # 保持历史数据在窗口大小以内
        if len(self.price_history[tick.symbol]) > self.window_size:
            self.price_history[tick.symbol] = self.price_history[tick.symbol][-self.window_size:]
        if len(self.volume_history[tick.symbol]) > self.window_size:
            self.volume_history[tick.symbol] = self.volume_history[tick.symbol][-self.window_size:]

    def calculate_technical_factors(self, tick: Tick) -> Dict[str, float]:
        """计算技术面因子"""
        factors = {}
        prices = self.price_history.get(tick.symbol, [])
        volumes = self.volume_history.get(tick.symbol, [])
        
        if len(prices) >= 2:
            # 简单收益率
            factors["return"] = (prices[-1] - prices[-2]) / prices[-2]
            
            # 移动平均线
            if len(prices) >= 5:
                factors["ma5"] = sum(prices[-5:]) / 5
            if len(prices) >= 10:
                factors["ma10"] = sum(prices[-10:]) / 10
            if len(prices) >= 20:
                factors["ma20"] = sum(prices[-20:]) / 20
                
                # 移动平均线交叉
                if len(prices) >= 21:
                    ma5_prev = sum(prices[-6:-1]) / 5
                    ma10_prev = sum(prices[-11:-1]) / 10
                    factors["ma5_ma10_cross"] = 1.0 if factors["ma5"] > factors["ma10"] and ma5_prev < ma10_prev else -1.0 if factors["ma5"] < factors["ma10"] and ma5_prev > ma10_prev else 0.0
        
        # 成交量相关因子
        if len(volumes) >= 5:
            factors["volume_ma5"] = sum(volumes[-5:]) / 5
            factors["volume_change"] = (volumes[-1] - volumes[-2]) / volumes[-2] if volumes[-2] > 0 else 0.0
        
        # 波动率
        if len(prices) >= 10:
            returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
            mean_return = sum(returns) / len(returns)
            variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
            factors["volatility"] = math.sqrt(variance)
        
        # 相对强弱指数 (RSI)
        if len(prices) >= 14:
            gains = []
            losses = []
            for i in range(1, len(prices)):
                change = prices[i] - prices[i-1]
                if change > 0:
                    gains.append(change)
                    losses.append(0)
                else:
                    gains.append(0)
                    losses.append(abs(change))
            
            if len(gains) >= 14:
                avg_gain = sum(gains[-14:]) / 14
                avg_loss = sum(losses[-14:]) / 14
                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    rsi = 100 - (100 / (1 + rs))
                    factors["rsi"] = rsi
        
        # 布林带
        if len(prices) >= 20:
            ma20 = sum(prices[-20:]) / 20
            std = math.sqrt(sum((p - ma20) ** 2 for p in prices[-20:]) / 20)
            upper_band = ma20 + 2 * std
            lower_band = ma20 - 2 * std
            factors["bollinger_upper"] = upper_band
            factors["bollinger_lower"] = lower_band
            factors["bollinger_width"] = (upper_band - lower_band) / ma20
            factors["bollinger_position"] = (prices[-1] - lower_band) / (upper_band - lower_band) if upper_band > lower_band else 0.5
        
        return factors

    def calculate_fundamental_factors(self, fundamental_data: Dict[str, float]) -> Dict[str, float]:
        """计算基本面因子"""
        factors = {}
        
        # 盈利能力
        if "roe" in fundamental_data:
            factors["roe"] = fundamental_data["roe"]
        if "pe_ttm" in fundamental_data and fundamental_data["pe_ttm"] > 0:
            factors["pe_ttm"] = fundamental_data["pe_ttm"]
            factors["earnings_yield"] = 1 / fundamental_data["pe_ttm"]
        
        # 成长能力
        if "revenue_yoy" in fundamental_data:
            factors["revenue_yoy"] = fundamental_data["revenue_yoy"]
        
        # 估值因子
        if "pb" in fundamental_data and fundamental_data["pb"] > 0:
            factors["pb"] = fundamental_data["pb"]
        if "ps" in fundamental_data and fundamental_data["ps"] > 0:
            factors["ps"] = fundamental_data["ps"]
        
        return factors

    def calculate_all_factors(self, tick: Tick, fundamental_data: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """计算所有因子"""
        self.update(tick)
        factors = self.calculate_technical_factors(tick)
        if fundamental_data:
            factors.update(self.calculate_fundamental_factors(fundamental_data))
        return factors
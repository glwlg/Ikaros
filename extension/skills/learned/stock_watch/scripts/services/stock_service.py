"""
股票行情服务 - 新浪主源 + 腾讯备源（与 a-stock-data 行情层一致）
"""
import logging
import math
import re
import httpx

logger = logging.getLogger(__name__)

SINA_QUOTE_URL = "http://hq.sinajs.cn/list="
SINA_SEARCH_URL = "https://suggest3.sinajs.cn/suggest/type=11,12,13,14,15,22,25&key="
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
HEADERS = {"Referer": "https://finance.sina.com.cn/"}
TENCENT_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://finance.qq.com/",
}
STOCK_MARKET_TYPES = {"11": "沪A", "12": "深A"}
ETF_MARKET_TYPES = {"22", "25"}
SH_INDEX_CODES = {"000300", "000905", "000016", "000688", "000852", "000010"}


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value in (None, "", "-"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_quote_code(raw: str) -> str:
    code = str(raw or "").strip().lower()
    if not code:
        return ""
    if code.startswith(("sh", "sz", "bj")) and len(code) >= 8:
        return code
    digits = re.sub(r"\D", "", code)
    if len(digits) != 6:
        return code
    if digits.startswith("92") or digits.startswith(("43", "83", "87")):
        return f"bj{digits}"
    if digits in SH_INDEX_CODES or digits.startswith(("5", "6", "9")):
        return f"sh{digits}"
    return f"sz{digits}"


def _quote_row(
    *,
    code: str,
    name: str,
    price: float,
    change: float,
    percent: float,
    open_price: float = 0.0,
    high: float = 0.0,
    low: float = 0.0,
    yesterday_close: float = 0.0,
    source: str = "sina",
    pe_ttm: float = 0.0,
    pb: float = 0.0,
) -> dict:
    return {
        "code": code,
        "name": name,
        "price": price,
        "change": round(change, 2),
        "percent": round(percent, 2),
        "open": open_price,
        "high": high,
        "low": low,
        "yesterday_close": yesterday_close,
        "source": source,
        "pe_ttm": pe_ttm,
        "pb": pb,
    }


def _parse_sina_quote_content(content: str) -> list[dict]:
    results: list[dict] = []
    for line in str(content or "").strip().split("\n"):
        if not line or "=" not in line:
            continue
        match = re.match(r'var hq_str_(\w+)="(.*)";?', line)
        if not match:
            continue
        code = match.group(1)
        data = match.group(2)
        if not data:
            continue
        parts = data.split(",")
        if len(parts) < 32:
            continue
        try:
            name = parts[0]
            open_price = _safe_float(parts[1])
            yesterday_close = _safe_float(parts[2])
            current_price = _safe_float(parts[3])
            high = _safe_float(parts[4])
            low = _safe_float(parts[5])
            change = current_price - yesterday_close
            percent = (change / yesterday_close * 100) if yesterday_close else 0
            results.append(
                _quote_row(
                    code=code,
                    name=name,
                    price=current_price,
                    change=change,
                    percent=percent,
                    open_price=open_price,
                    high=high,
                    low=low,
                    yesterday_close=yesterday_close,
                    source="sina",
                )
            )
        except (ValueError, IndexError) as exc:
            logger.warning("Failed to parse Sina stock data for %s: %s", code, exc)
    return results


async def _fetch_sina_quotes(stock_codes: list[str]) -> list[dict]:
    if not stock_codes:
        return []
    codes_str = ",".join(stock_codes)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{SINA_QUOTE_URL}{codes_str}",
                headers=HEADERS,
            )
            response.raise_for_status()
            content = response.content.decode("gbk", errors="ignore")
            return _parse_sina_quote_content(content)
    except httpx.HTTPStatusError as exc:
        logger.error("HTTP error fetching Sina stock quotes: %s", exc)
    except Exception as exc:
        logger.error("Error fetching Sina stock quotes: %s", exc)
    return []


def _parse_tencent_quote_content(content: str) -> list[dict]:
    """Parse Tencent qt.gtimg.cn payload (a-stock-data §1.2 field map)."""
    results: list[dict] = []
    for line in str(content or "").strip().split(";"):
        line = line.strip()
        if not line or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1].lower()
        try:
            payload = line.split('"')[1]
        except IndexError:
            continue
        vals = payload.split("~")
        if len(vals) < 49:
            continue
        price = _safe_float(vals[3])
        yesterday_close = _safe_float(vals[4])
        open_price = _safe_float(vals[5])
        change = _safe_float(vals[31], price - yesterday_close)
        percent = _safe_float(
            vals[32],
            (change / yesterday_close * 100) if yesterday_close else 0,
        )
        high = _safe_float(vals[33])
        low = _safe_float(vals[34])
        pe_ttm = _safe_float(vals[39]) if len(vals) > 39 else 0.0
        pb = _safe_float(vals[46]) if len(vals) > 46 else 0.0
        name = str(vals[1] or "").strip() or key
        if price <= 0 and yesterday_close <= 0:
            continue
        results.append(
            _quote_row(
                code=key,
                name=name,
                price=price,
                change=change,
                percent=percent,
                open_price=open_price,
                high=high,
                low=low,
                yesterday_close=yesterday_close,
                source="tencent",
                pe_ttm=pe_ttm,
                pb=pb,
            )
        )
    return results


async def _fetch_tencent_quotes(stock_codes: list[str]) -> list[dict]:
    if not stock_codes:
        return []
    codes = [_normalize_quote_code(code) for code in stock_codes]
    codes = [code for code in codes if code]
    if not codes:
        return []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{TENCENT_QUOTE_URL}{','.join(codes)}",
                headers=TENCENT_HEADERS,
            )
            response.raise_for_status()
            content = response.content.decode("gbk", errors="ignore")
            return _parse_tencent_quote_content(content)
    except httpx.HTTPStatusError as exc:
        logger.error("HTTP error fetching Tencent stock quotes: %s", exc)
    except Exception as exc:
        logger.error("Error fetching Tencent stock quotes: %s", exc)
    return []


async def fetch_stock_quotes(stock_codes: list[str]) -> list[dict]:
    """
    批量获取股票实时行情（新浪优先，缺失/失败时腾讯补齐）。

    Args:
        stock_codes: 股票代码列表，如 ["sh601006", "sz000001"]

    Returns:
        [{"code": "sh601006", "name": "大秦铁路", "price": 7.88,
          "change": 0.12, "percent": 1.55, "open": 7.80, "high": 7.90, "low": 7.75}, ...]
    """
    if not stock_codes:
        return []

    requested = []
    seen: set[str] = set()
    for raw in stock_codes:
        code = _normalize_quote_code(raw)
        if not code or code in seen:
            continue
        seen.add(code)
        requested.append(code)

    sina_rows = await _fetch_sina_quotes(requested)
    by_code = {
        str(item.get("code") or "").strip().lower(): item
        for item in sina_rows
        if str(item.get("code") or "").strip()
        and float(item.get("price") or 0) > 0
    }
    missing = [code for code in requested if code not in by_code]
    if missing:
        for item in await _fetch_tencent_quotes(missing):
            code = str(item.get("code") or "").strip().lower()
            if code and code not in by_code and float(item.get("price") or 0) > 0:
                by_code[code] = item

    # Preserve request order
    return [by_code[code] for code in requested if code in by_code]



def _etf_exchange_code(raw_code: str) -> str:
    code = str(raw_code or "").strip().lower()
    if code.startswith(("sh", "sz")) and len(code) == 8:
        return code
    if code.startswith("of") and len(code) == 8:
        code = code[2:]
    if not re.fullmatch(r"\d{6}", code):
        return ""
    if code.startswith("5"):
        return f"sh{code}"
    if code.startswith(("15", "16", "18")):
        return f"sz{code}"
    return ""


def _normalize_sina_search_item(parts: list[str]) -> dict | None:
    if len(parts) < 4:
        return None

    market_type = str(parts[1] or "").strip()
    stock_name = str(parts[4] if len(parts) > 4 and parts[4] else parts[0]).strip()
    raw_code = str(parts[2] or "").strip()
    full_code = str(parts[3] or "").strip().lower()

    if market_type in STOCK_MARKET_TYPES:
        return {
            "code": full_code,
            "name": stock_name,
            "market": STOCK_MARKET_TYPES[market_type],
            "_priority": 0,
        }

    if market_type in ETF_MARKET_TYPES and "ETF" in stock_name.upper():
        code = _etf_exchange_code(raw_code or full_code)
        if not code:
            return None
        return {
            "code": code,
            "name": stock_name,
            "market": "ETF",
            "_priority": 1 if market_type == "22" else 2,
        }

    return None


def _parse_sina_search_results(content: str) -> list[dict]:
    match = re.search(r'var suggestvalue="(.*)";?', content)
    if not match:
        return []

    data = match.group(1)
    if not data:
        return []

    indexed: dict[str, dict] = {}
    order: list[str] = []
    for item in data.split(";"):
        normalized = _normalize_sina_search_item(item.split(","))
        if not normalized:
            continue

        code_key = str(normalized.get("code") or "").strip().lower()
        if not code_key:
            continue
        if code_key not in indexed:
            order.append(code_key)
            indexed[code_key] = normalized
            continue
        if int(normalized.get("_priority") or 99) < int(
            indexed[code_key].get("_priority") or 99
        ):
            indexed[code_key] = normalized

    results = []
    for code_key in order:
        item = dict(indexed[code_key])
        item.pop("_priority", None)
        results.append(item)
    return results


async def search_stock_by_name(keyword: str) -> list[dict]:
    """
    根据名称或代码模糊搜索股票
    
    Args:
        keyword: 搜索关键词，如 "仙鹤" 或 "603733"
    
    Returns:
        [{"code": "sh603733", "name": "仙鹤股份", "market": "沪A"}, ...]
    
    新浪API返回格式: "名称,市场类型,纯代码,完整代码,名称,..."
    例如: "仙鹤股份,11,603733,sh603733,仙鹤股份,,仙鹤股份,99,1,,,"
    """
    if not keyword:
        return []
    
    results = []
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{SINA_SEARCH_URL}{keyword}",
                headers=HEADERS
            )
            response.raise_for_status()
            
            content = response.content.decode("gbk", errors="ignore")
            
            results = _parse_sina_search_results(content)
                
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error searching stock: {e}")
    except Exception as e:
        logger.error(f"Error searching stock: {e}")
    
    return results


def _format_push_direction(stock: dict, previous_prices: dict[str, float] | None) -> str:
    if not previous_prices:
        return ""

    code = str(stock.get("code") or "").strip()
    if not code or code not in previous_prices:
        return ""

    current_price = float(stock.get("price") or 0)
    previous_price = previous_prices[code]
    if current_price > previous_price:
        return "↑"
    if current_price < previous_price:
        return "↓"
    return ""


def _positive_number(value) -> float:
    try:
        normalized = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return normalized if math.isfinite(normalized) and normalized > 0 else 0.0


def _format_signed_amount(value: float) -> str:
    normalized = 0.0 if abs(value) < 0.005 else value
    return f"{normalized:+.2f}" if normalized else "0.00"


def _format_signed_amount_compact(value: float) -> str:
    """双列明细用的金额：优先整数，尽量短。"""
    normalized = 0.0 if abs(value) < 0.005 else value
    if not normalized:
        return "0"
    # 绝对值较大时取整，避免 2533.50 这种占宽度。
    if abs(normalized) >= 100 or abs(normalized - round(normalized)) < 0.005:
        return f"{int(round(normalized)):+d}"
    return f"{normalized:+.2f}"


def _format_price(value: float) -> str:
    """格式化价格，去掉多余尾零，并保留低价标的有效精度。"""
    try:
        price = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(price):
        return str(value)
    text = f"{price:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _format_quantity(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _format_lots(quantity: float) -> str:
    """仓位按手显示，100 股 = 1 手。"""
    try:
        shares = float(quantity)
    except (TypeError, ValueError):
        return "0手"
    if not math.isfinite(shares) or shares <= 0:
        return "0手"
    lots = shares / 100.0
    if abs(lots - round(lots)) < 1e-9:
        return f"{int(round(lots))}手"
    text = f"{lots:.2f}".rstrip("0").rstrip(".")
    return f"{text}手"


def _format_percent(value: float) -> str:
    """格式化涨跌幅百分比数值，去掉多余尾零。"""
    try:
        percent = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(percent):
        return str(value)
    text = f"{percent:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _format_percent_compact(value: float) -> str:
    """双列明细用的百分比：尽量短。"""
    try:
        percent = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(percent):
        return str(value)
    if abs(percent) < 0.05:
        return "0"
    if abs(percent) >= 10:
        return f"{percent:+.0f}"
    text = f"{percent:+.1f}".rstrip("0").rstrip(".")
    return text or "0"


def _format_holding_ratio(percent: float) -> str:
    """
    持仓盈亏比例。

    极端情况（例如成本极低）会把超大百分比压缩成“倍/万倍”，
    如 +7939900% -> +7.9万倍。
    """
    try:
        value = float(percent)
    except (TypeError, ValueError):
        return "0%"
    if not math.isfinite(value):
        return "0%"
    if abs(value) < 0.05:
        return "0%"

    # >= 10 倍时切到“倍”单位，避免百分比位数爆炸。
    if abs(value) >= 1000:
        times = abs(value) / 100.0
        sign = "+" if value > 0 else "-"
        if times >= 10000:
            body = f"{times / 10000:.1f}".rstrip("0").rstrip(".") + "万倍"
        elif times >= 100:
            body = f"{times:.0f}倍"
        else:
            body = f"{times:.1f}".rstrip("0").rstrip(".") + "倍"
        return f"{sign}{body}"

    return f"{_format_percent_compact(value)}%"


def _format_stock_name(name: str, width: int = 4) -> str:
    """股票名称最多 4 个字，不足时用全角空格补齐，便于双列对齐。"""
    text = str(name or "")
    if len(text) > width:
        text = text[:width]
    if len(text) < width:
        text = text + ("　" * (width - len(text)))
    return text


def _visible_text(text: str) -> str:
    # markdown 加粗不影响实际显示宽度
    return text.replace("**", "")


def _display_width(text: str) -> int:
    """估算 Telegram 等客户端中的显示宽度。

    半角空格在 Telegram 上偏窄，大约 2 个才顶 1 个普通半角字符位，
    因此这里用“半单位”计量：
    - 半角空格 = 1
    - 普通半角字符 = 2
    - CJK / 全角 / emoji = 4
    """
    width = 0
    for char in _visible_text(text):
        if char == " ":
            width += 1
            continue
        code = ord(char)
        # 粗略按 CJK / 全角 / emoji 双宽处理，便于手机气泡双列对齐。
        if (
            code >= 0x1100
            and (
                code <= 0x115F
                or 0x2E80 <= code <= 0xA4CF
                or 0xAC00 <= code <= 0xD7A3
                or 0xF900 <= code <= 0xFAFF
                or 0xFE10 <= code <= 0xFE6F
                or 0xFF00 <= code <= 0xFF60
                or 0xFFE0 <= code <= 0xFFE6
                or 0x1F300 <= code <= 0x1FAFF
            )
        ):
            width += 4
        else:
            width += 2
    return width


def _pad_display(text: str, width: int) -> str:
    pad = width - _display_width(text)
    if pad <= 0:
        return text
    # pad 以半单位计，1 个半角空格 = 1 半单位。
    return text + (" " * pad)


def _format_dual_columns(items: list[str], gap: int = 4) -> list[str]:
    """将条目两两配对，并按统一左列宽度对齐。"""
    pairs: list[tuple[str, str | None]] = []
    for index in range(0, len(items), 2):
        left = items[index]
        right = items[index + 1] if index + 1 < len(items) else None
        pairs.append((left, right))

    left_width = 0
    for left, _right in pairs:
        for line in left.split("\n"):
            left_width = max(left_width, _display_width(line))

    rows: list[str] = []
    for left, right in pairs:
        if not right:
            rows.append(left)
            continue

        left_lines = left.split("\n")
        right_lines = right.split("\n")
        line_count = max(len(left_lines), len(right_lines))
        left_lines.extend([""] * (line_count - len(left_lines)))
        right_lines.extend([""] * (line_count - len(right_lines)))
        for left_line, right_line in zip(left_lines, right_lines):
            if right_line:
                rows.append(f"{_pad_display(left_line, left_width + gap)}{right_line}")
            else:
                rows.append(left_line)
    return rows


def _position_map(positions: list[dict] | None) -> dict[str, dict[str, float]]:
    indexed: dict[str, dict[str, float]] = {}
    for item in positions or []:
        code = str(item.get("stock_code") or item.get("code") or "").strip().lower()
        quantity = _positive_number(item.get("position_quantity"))
        cost_price = _positive_number(item.get("cost_price"))
        if code and quantity and cost_price:
            indexed[code] = {
                "quantity": quantity,
                "cost_price": cost_price,
            }
    return indexed


def format_stock_message(
    stocks: list[dict],
    previous_prices: dict[str, float] | None = None,
    positions: list[dict] | None = None,
) -> str:
    """
    格式化股票行情消息（统一双列；有持仓时每只股票两行）

    Args:
        stocks: fetch_stock_quotes 返回的股票列表
        previous_prices: 上一次成功推送时的股票价格，用于展示本次推送相对方向
        positions: 自选股持仓数量与单位成本，用于计算今日和持仓盈亏

    Returns:
        格式化的消息文本
    """
    if not stocks:
        return "暂无股票数据"

    position_by_code = _position_map(positions)
    position_details: dict[str, str] = {}
    daily_profit_total = 0.0
    holding_profit_total = 0.0
    holding_cost_total = 0.0

    for stock in stocks:
        code = str(stock.get("code") or "").strip().lower()
        position = position_by_code.get(code)
        if not position:
            continue
        quantity = position["quantity"]
        cost_price = position["cost_price"]
        current_price = float(stock.get("price") or 0)
        daily_profit = float(stock.get("change") or 0) * quantity
        holding_profit = (current_price - cost_price) * quantity
        holding_cost = cost_price * quantity
        holding_percent = (holding_profit / holding_cost * 100) if holding_cost else 0

        daily_profit_total += daily_profit
        holding_profit_total += holding_profit
        holding_cost_total += holding_cost
        position_details[code] = (
            f"{_format_lots(quantity)} "
            f"今{_format_signed_amount_compact(daily_profit)} "
            f"浮{_format_signed_amount_compact(holding_profit)}"
            f"({_format_holding_ratio(holding_percent)})"
        )

    lines = ["📈 **自选股行情**\n"]
    if position_details:
        holding_percent_total = (
            holding_profit_total / holding_cost_total * 100 if holding_cost_total else 0
        )
        lines.extend(
            [
                f"💰 **今日盈亏：{_format_signed_amount(daily_profit_total)}元**",
                (
                    f"💼 持仓盈亏：{_format_signed_amount(holding_profit_total)}元 "
                    f"({_format_holding_ratio(holding_percent_total)})\n"
                ),
            ]
        )
    formatted_items = []

    for stock in stocks:
        # 涨跌符号和颜色提示
        if stock["change"] > 0:
            emoji = "🔴"
            sign = "+"
        elif stock["change"] < 0:
            emoji = "🟢"
            sign = ""
        else:
            emoji = "⚪"
            sign = ""

        name = _format_stock_name(stock["name"], width=4)
        direction = _format_push_direction(stock, previous_prices)
        direction_text = f"{direction}" if direction else ""
        percent_text = _format_percent(stock["percent"])
        item_str = (
            f"{emoji}{name} {_format_price(stock['price'])} "
            f"{sign}{percent_text}%{direction_text}"
        )
        # 涨跌超过 1 个点加粗；对齐按可见宽度计算，忽略 **。
        if abs(float(stock.get("percent") or 0)) > 1.0:
            item_str = f"**{item_str}**"

        detail = position_details.get(str(stock.get("code") or "").strip().lower())
        if detail:
            formatted_items.append(f"{item_str}\n{detail}")
        else:
            formatted_items.append(item_str)

    lines.extend(_format_dual_columns(formatted_items))
    return "\n".join(lines)


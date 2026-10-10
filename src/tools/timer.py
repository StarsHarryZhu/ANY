import datetime

from tzlocal import get_localzone

# 星期名写死成英文表，不用 strftime("%A")：%A 走 locale，同一份代码在中文系统上会输出
# "星期六"。工具结果整段进 context 回传给模型，输出形状必须与运行环境无关。
# 索引与 datetime.weekday() 对齐（0 = 周一）。
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# 秒级格式。datetime.isoformat() 默认带微秒，模型用不上，还会让它以为有亚秒精度。
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _format_offset(offset: datetime.timedelta) -> str:
    # "+08:00" 这种带冒号的形式。用算术取时/分，而不是切 strftime("%z") 的字符串：
    # "%z" 给的是 "+0800"，负偏移和半小时（+05:30）、三刻钟（+05:45）偏移切片都得另想。
    total_minutes = int(offset.total_seconds() // 60)
    sign = "-" if total_minutes < 0 else "+"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


class current_time():
    # 工具 ID，十六进制写。值本身是 int，get_method() 原样交出去；preset.json 里写十进制
    # （JSON 没有十六进制字面量）或 "0x01" 字符串。0 保留给 no-restriction 哨兵。
    ID = 0x01

    DESCRIPTION = (
        "Get the current local date and time of the machine running this program, at "
        "second resolution. Returns the machine's IANA timezone name and UTC offset "
        "together with the local time, the UTC time and the unix timestamp. Use this "
        "whenever an answer depends on the present moment."
    )

    def get_method(self) -> dict:
        # 名字取类名本身，不手抄字符串：类改名时注册表跟着变，不可能对不上。
        # 本工具不收参数，schema 是个空对象（两个 provider 都接受这个形状）。
        return {
            "name": type(self).__name__,
            "id": self.ID,
            "description": self.DESCRIPTION,
            "parameters": {"type": "object", "properties": {}},
        }


    def toolcall(self) -> dict:
        # 时间值走 datetime.now().astimezone()：只用操作系统的本地时区规则，本机此刻的墙上
        # 时间（含夏令时）就是对的，没有额外依赖，也没有失败模式。
        local = datetime.datetime.now().astimezone()
        offset = local.utcoffset()
        # 时区名单独取：标准库只能给固定偏移（datetime.timezone），产不出 IANA 名。
        # tzlocal 是这件事上被广泛采用的库，三个平台都盖：Unix 读 /etc/timezone、/etc/localtime
        # 等，Windows 从注册表映射到 IANA——它声明的 tzdata 依赖在 Windows 上会自动装上
        # （那个平台没有系统 tz 数据库，光有标准库的 zoneinfo 查不到）。
        # 取不到名字不该让整个工具失败：时间本身已经有了，这不是仓库代码出错，不往上抛。
        # 退成 "UTC+08:00" 而不是 tzname()/str(tzinfo)：那是操作系统给的缩写（实测
        # now().astimezone().tzinfo 的 str() 是 "EDT" 这种），CST 既是中国标准时间也能是美国
        # 中部时间，固定偏移至少不含糊。刻意不接 BaseException：Ctrl-C 照旧穿出去。
        try:
            timezone_name = str(get_localzone())
        except Exception:
            timezone_name = f"UTC{_format_offset(offset)}" if offset else "UTC"
        utc = local.astimezone(datetime.timezone.utc)
        return {
            "local_time": local.strftime(TIME_FORMAT),
            "date": local.strftime("%Y-%m-%d"),
            "weekday": WEEKDAYS[local.weekday()],
            "timezone": timezone_name,
            "utc_offset": _format_offset(offset),
            "utc_time": utc.strftime(TIME_FORMAT),
            "unix_timestamp": int(local.timestamp()),
        }

import requests

# 顺序是有意的：三个源里只有 ip-api.com 有 district（区级）字段，所以它排第一；它也是免费
# 端点里唯一只提供 HTTP 的（HTTPS 要付费 key）。后两个是 HTTPS，都没有 district。
# 每个源返回同一套键，缺的字段给 None——键集固定，模型只学一种形状，"这个源不提供"和
# "这个源挂了"才分得清。谁答的写在 source 里。
# 不并发：正常情况第一个源就答了，并发只会让失败路径快一点，却把三个源的限流额度同时消耗掉。
#
# 超时是必需的：requests 默认不超时，网络黑洞会让这次工具调用永远挂住，整个 REPL 卡死。
# (连接, 读取) 分开给——最坏情况要串完三个源，连接阶段压到 3 秒。
TIMEOUT = (3, 5)

# requests 默认 UA 是 "python-requests/x.y"，是各家端点常见的拦截特征。自报家门的 UA 比
# 假装浏览器诚实，也省掉一整类莫名其妙的 403。
HEADERS = {"User-Agent": "ANY/1.0 (terminal LLM chat REPL; current_location tool)"}

# ip-api 的字段裁剪。status 必须显式列上：它用 HTTP 200 报业务失败，失败原因在 body 的
# status/message 里，丢了它就会把 {"status": "fail"} 当成一条空数据收下。
IP_API_FIELDS = "status,message,country,countryCode,region,regionName,city,district,lat,lon,timezone,query"

# 返回形状的底表：十个键一个不少，模型只学一种形状。
EMPTY_RESULT = {
    "ip": None,
    "country": None,
    "country_code": None,
    "region": None,
    "city": None,
    "district": None,
    "latitude": None,
    "longitude": None,
    "timezone": None,
    "source": None,
}


def _result(source: str, **fields) -> dict:
    # 以空表为底再覆盖：某个源少给字段，返回形状也不会塌成九个键。source 在底表之后写死，
    # 不可能忘。
    # 多出来的键只可能是源码里字段名写错了（latitude 打成 lat），那是仓库代码 bug，直接抛：
    # toolcall 会当成"这个源不可用"换下一个，最后三个源一起把原因报出来。
    unknown = fields.keys() - EMPTY_RESULT.keys()
    if unknown:
        raise ValueError(f"unknown field(s): {', '.join(sorted(unknown))}")
    return EMPTY_RESULT | {"source": source} | fields


def _from_ip_api() -> dict:
    response = requests.get(
        "http://ip-api.com/json/",
        params={"fields": IP_API_FIELDS},
        timeout=TIMEOUT,
        headers=HEADERS,
    )
    response.raise_for_status()  # 限流是 HTTP 429，走这里
    payload = response.json()
    if payload.get("status") != "success":
        raise RuntimeError(f"query refused: {payload.get('message')!r}")
    return _result(
        "ip-api.com",
        ip=payload.get("query"),
        country=payload.get("country"),
        country_code=payload.get("countryCode"),
        # ip-api 的 region 是代码（"SH"），regionName 才是名字，别取错
        region=payload.get("regionName"),
        city=payload.get("city"),
        # 没数据时它给的是空串（不是缺失），空串不是信息，统一成 None
        district=payload.get("district") or None,
        latitude=payload.get("lat"),
        longitude=payload.get("lon"),
        timezone=payload.get("timezone"),
    )


def _from_ipwho_is() -> dict:
    response = requests.get("https://ipwho.is/", timeout=TIMEOUT, headers=HEADERS)
    response.raise_for_status()
    payload = response.json()
    # 应用层失败是 HTTP 200 + success:false（"Invalid IP address" 这类），不看这个标志位
    # 就会收下一条空数据。
    if not payload.get("success"):
        raise RuntimeError(f"query refused: {payload.get('message')!r}")
    # 时区是嵌套对象。形状不对就当没有——丢一个字段不值得让整个源作废。
    timezone = payload.get("timezone")
    timezone = timezone.get("id") if isinstance(timezone, dict) else None
    return _result(
        "ipwho.is",
        ip=payload.get("ip"),
        country=payload.get("country"),
        country_code=payload.get("country_code"),
        region=payload.get("region"),
        city=payload.get("city"),
        # 这个源没有区级字段：键照留、值给 None
        latitude=payload.get("latitude"),
        longitude=payload.get("longitude"),
        timezone=timezone,
    )


def _from_ipapi_co() -> dict:
    response = requests.get("https://ipapi.co/json/", timeout=TIMEOUT, headers=HEADERS)
    response.raise_for_status()
    payload = response.json()
    # 限流是 HTTP 429（上面的 raise_for_status 就挡了），但有些错误是 HTTP 200 + error 字段，
    # 两种都要挡。
    if payload.get("error"):
        raise RuntimeError(f"query refused: {payload.get('reason') or payload.get('message')!r}")
    return _result(
        "ipapi.co",
        ip=payload.get("ip"),
        country=payload.get("country_name"),
        country_code=payload.get("country_code"),
        region=payload.get("region"),
        city=payload.get("city"),
        latitude=payload.get("latitude"),
        longitude=payload.get("longitude"),
        timezone=payload.get("timezone"),
    )


# (名字, 取数函数)。名字只用于错误信息：全挂时要把三个源各自的失败原因说清楚，否则模型和
# 用户都看不出是断网、被限流，还是解析炸了。
SOURCES = (
    ("ip-api.com", _from_ip_api),
    ("ipwho.is", _from_ipwho_is),
    ("ipapi.co", _from_ipapi_co),
)


class current_location():
    # 见 timer.py 里同名属性的注释（ID 十六进制写、0 保留给哨兵）。
    ID = 0x02

    DESCRIPTION = (
        "Get the approximate geographic location of this machine from its public IP "
        "address: country, region, city, district (only when the answering service "
        "provides one), coordinates and the location's timezone. IP geolocation is "
        "coarse (a city at best, and an ISP's egress point rather than the device), so "
        "treat the result as approximate. Use it when the user asks where they are."
    )

    def get_method(self) -> dict:
        return {
            "name": type(self).__name__,
            "id": self.ID,
            "description": self.DESCRIPTION,
            "parameters": {"type": "object", "properties": {}},
        }


    def toolcall(self) -> dict:
        # 顺序回退：三个源的形状差异（字段名、有没有 district、失败怎么表达）都在各 _from_*
        # 里抹平，这里只管顺序和错误汇总。
        failures = []
        for name, fetch in SOURCES:
            try:
                return fetch()
            except Exception as error:
                # 捕 Exception：超时、连不上、DNS 失败、JSON 解析失败、限流，以及各源自己抛的
                # "业务失败"——都只说明"这个源不可用"，换下一个。刻意不接 BaseException：
                # Ctrl-C 要能中断这次工具调用（穿到循环层的 KeyboardInterrupt 分支去）。
                failures.append(f"{name}: {type(error).__name__}: {error}")
        # 三个都挂才抛。抛是对的，不能返回 {"error": ...}：_tool_console 里写着，那样与
        # tool_run 失败路径的输出同形，调用方分不出来。抛出去由 tool_run 转成带 tool_error
        # 标志的错误文本，模型因此知道这轮没数据，可以换个说法或让用户稍后再问。
        detail = "; ".join(failures) if failures else "no sources configured"
        raise RuntimeError(f"all location sources failed: {detail}")

package com.zoop.company.market;

import java.net.URI;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.locks.ReentrantLock;

import com.zoop.company.market.dto.CompanyPriceResponse;
import com.zoop.company.market.dto.CompanyQuoteResponse;
import org.springframework.http.MediaType;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@Component
public class TossMarketClient {
    private static final String AUTH_FAILED = "토스증권 인증에 실패했어요. 시세 키를 확인해 주세요.";
    private static final String FORMAT_CHANGED = "토스증권 응답 형식을 읽지 못했어요.";
    private static final String TEMPORARY = "시세 출처에 잠시 연결하지 못했어요. 잠시 후 다시 시도해 주세요.";
    private final CompanyMarketSettings settings;
    private final RestClient client;
    private final ObjectMapper mapper;
    private final Clock clock;
    private final ReentrantLock tokenLock = new ReentrantLock();
    private volatile String token;
    private volatile Instant tokenExpires = Instant.EPOCH;

    public TossMarketClient(CompanyMarketSettings settings, ObjectMapper mapper, Clock clock) {
        this.settings = settings;
        this.mapper = mapper;
        this.clock = clock;
        var httpClient = java.net.http.HttpClient.newBuilder().connectTimeout(settings.timeout()).build();
        var requestFactory = new JdkClientHttpRequestFactory(httpClient);
        requestFactory.setReadTimeout(settings.timeout());
        this.client = RestClient.builder().baseUrl(settings.tossBaseUrl()).requestFactory(requestFactory).build();
    }

    public CompanyQuoteResponse quote(String companyId, String exchange, String code) {
        if (!"toss".equalsIgnoreCase(settings.quoteProvider())
                || blank(settings.tossClientId()) || blank(settings.tossClientSecret())) {
            return CompanyQuoteResponse.unavailable(companyId, "not_connected", "토스증권 시세 키가 설정되지 않았어요.");
        }
        if (!("KRX".equals(exchange) || "NASDAQ".equals(exchange) || "NYSE".equals(exchange) || "AMEX".equals(exchange))) {
            return CompanyQuoteResponse.unavailable(companyId, "unsupported_symbol", "이 종목은 토스증권 시세 조회를 지원하지 않아요.");
        }
        try {
            JsonNode priceRoot = get("/api/v1/prices", Map.of("symbols", code));
            JsonNode price = matching(priceRoot.path("result"), code);
            if (price == null) return CompanyQuoteResponse.unavailable(companyId, "unsupported_symbol", "토스증권에서 이 종목을 찾지 못했어요.");
            // Absent values are a normal "no data"; a present value in the wrong shape is a provider format failure.
            Double last = strictNumber(price.get("lastPrice"));
            String currency = strictText(price.get("currency"));
            if (last == null || currency == null) {
                return CompanyQuoteResponse.unavailable(companyId, "no_data", "토스증권에 현재가 또는 통화 정보가 없어요.");
            }
            // A missing observation time keeps the price with quote.asOf = null; an unreadable one is a format failure.
            String timestamp = strictText(price.get("timestamp"));
            Instant asOf = timestamp == null ? null : instant(timestamp);
            if (timestamp != null && asOf == null) throw formatFailure();
            JsonNode stocks = get("/api/v1/stocks", Map.of("symbols", code));
            JsonNode stock = matching(stocks.path("result"), code);
            Double shares = stock == null ? null : number(stock.get("sharesOutstanding"));
            List<JsonNode> daily = dailyCandles(code, 3, null, null);
            // Daily candles are dated in the market's own calendar, so the quote's session day uses the same zone.
            String sessionDate = asOf == null ? null : asOf.atZone(marketZone(exchange)).toLocalDate().toString();
            // The 52-week range only uses candles from the year ending on the quote's session date.
            String windowStart = sessionDate == null ? null
                    : java.time.LocalDate.parse(sessionDate).minusDays(365).toString();
            JsonNode current = null, previous = null;
            Double high52 = null, low52 = null;
            String oldestDate = null;
            for (JsonNode candle : daily) {
                String day = text(candle.get("timestamp"));
                if (day == null || !day.matches("\\d{4}-\\d{2}-\\d{2}.*")) continue;
                day = day.substring(0, 10);
                if (oldestDate == null || day.compareTo(oldestDate) < 0) oldestDate = day;
                if (sessionDate != null && day.equals(sessionDate)) current = candle;
                if (sessionDate != null && day.compareTo(sessionDate) < 0 && (previous == null
                        || day.compareTo(text(previous.get("timestamp")).substring(0, 10)) > 0)) previous = candle;
                if (windowStart == null || day.compareTo(windowStart) < 0 || day.compareTo(sessionDate) > 0) continue;
                Double high = number(candle.get("highPrice")), low = number(candle.get("lowPrice"));
                if (high != null) high52 = high52 == null ? high : Math.max(high52, high);
                if (low != null) low52 = low52 == null ? low : Math.min(low52, low);
            }
            if (sessionDate == null || oldestDate == null
                    || java.time.LocalDate.parse(oldestDate).isAfter(java.time.LocalDate.parse(sessionDate).minusDays(365))) {
                high52 = null; low52 = null;
            }
            Double previousClose = previous == null ? null : number(previous.get("closePrice"));
            Double change = previousClose == null ? null : last - previousClose;
            Double changeRate = previousClose == null || previousClose == 0 ? null : change / previousClose;
            Double marketCap = shares == null ? null : shares * last;
            List<String> derived = new java.util.ArrayList<>();
            if (previousClose != null) derived.addAll(List.of("previousClose", "change", "changeRate"));
            if (high52 != null && low52 != null) derived.addAll(List.of("fiftyTwoWeekHigh", "fiftyTwoWeekLow"));
            if (marketCap != null) derived.add("marketCap");
            var quote = new CompanyQuoteResponse.QuoteValues(currency, last, asOf, previousClose, change, changeRate,
                    current == null ? null : number(current.get("highPrice")),
                    current == null ? null : number(current.get("lowPrice")),
                    current == null ? null : number(current.get("volume")), high52, low52, marketCap, shares, derived);
            return CompanyQuoteResponse.available(companyId,
                    new CompanyQuoteResponse.Source("toss", "토스증권", true, null, code, null), quote);
        } catch (MarketDataException exception) {
            throw exception;
        } catch (TossUnsupportedSymbolException exception) {
            return CompanyQuoteResponse.unavailable(companyId, "unsupported_symbol", "토스증권에서 이 종목을 찾지 못했어요.");
        } catch (RestClientException exception) {
            throw new MarketDataException(true);
        } catch (Exception exception) {
            throw new MarketDataException(false);
        }
    }

    /** Bar resolution the contract fixes per period: 1d=5m, 1w=1h, 1m=1d, 1y=1wk. */
    public static final Map<String, String> PERIOD_INTERVAL = Map.of("1d", "5m", "1w", "1h", "1m", "1d", "1y", "1wk");
    private static final ZoneId KST = ZoneId.of("Asia/Seoul");

    /**
     * getCompanyPrices over [from, to). Toss serves only 1-minute and daily candles, so 1d/1w are 1-minute bars and
     * 1y daily bars aggregated into the contract's fixed resolution (x-zoop.chartResolution); 1m is the daily bars as
     * they are. A point is a whole bucket (5 minutes, an hour, an exchange day or a Monday week) that overlaps
     * [from, to): the chart sends a point's own start back as to, and that point must come back with the same values.
     * A missing to is now and a missing from one period before it. 1d takes no from: it is the listing exchange's
     * regular session that is open at to, or the last one before it (FS040).
     */
    public CompanyPriceResponse prices(String companyId, String exchange, String code, String period,
            Instant from, Instant to) {
        if (!"toss".equalsIgnoreCase(settings.quoteProvider())
                || blank(settings.tossClientId()) || blank(settings.tossClientSecret())) {
            return CompanyPriceResponse.unavailable(companyId, period, "not_connected", "토스증권 시세 키가 설정되지 않았어요.");
        }
        if (!("KRX".equals(exchange) || "NASDAQ".equals(exchange) || "NYSE".equals(exchange) || "AMEX".equals(exchange))) {
            return CompanyPriceResponse.unavailable(companyId, period, "unsupported_symbol", "이 종목은 토스증권 시세 조회를 지원하지 않아요.");
        }
        String interval = PERIOD_INTERVAL.get(period);
        ZoneId zone = marketZone(exchange);
        Instant end = to != null ? to : clock.instant();
        Instant start = from != null ? from : periodStart(period, end);
        String sessionDate = null;
        try {
            List<CompanyPriceResponse.Point> points = List.of();
            if ("1d".equals(period)) {
                Session session = session("KRX".equals(exchange), end.minusNanos(1).atZone(zone).toLocalDate(), end, zone);
                start = session.open();
                end = end.isBefore(session.close()) ? end : session.close();
                sessionDate = session.date();
                // A session the calendar says was open but that has no bars is no_data, never the day before.
                points = minuteBuckets(code, zone, start, end, 300);
            } else if ("1h".equals(interval)) {
                points = minuteBuckets(code, zone, start, end, 3600);
            } else {
                boolean weekly = "1wk".equals(interval);
                // A daily bar starts at its exchange-local midnight; a week bucket at that week's Monday.
                Instant first = weekly ? PriceBars.weekStart(start, zone)
                        : start.atZone(zone).toLocalDate().atStartOfDay(zone).toInstant();
                // The next local Monday, not +168 hours: a DST week is 167 or 169 hours long.
                Instant last = weekly ? PriceBars.weekStart(end.minusNanos(1).atZone(zone).plusWeeks(1).toInstant(), zone) : end;
                List<PriceBars.Bar> daily = new java.util.ArrayList<>();
                for (JsonNode candle : dailyCandles(code, 10, last, first)) {
                    PriceBars.Bar bar = bar(candle, at -> at);
                    if (bar != null && !bar.start().isBefore(first) && bar.start().isBefore(last)) daily.add(bar);
                }
                points = weekly ? PriceBars.byWeek(daily, zone) : PriceBars.asIs(daily, zone);
            }
            if (points.isEmpty()) {
                return CompanyPriceResponse.unavailable(companyId, period, "no_data", "이 기간에는 거래된 시세가 없어요(휴장일 등).");
            }
            JsonNode stock = matching(get("/api/v1/stocks", Map.of("symbols", code)).path("result"), code);
            // Bars came back, so a missing stock row or currency is a provider format failure, not an absence of data.
            String currency = stock == null ? null : strictText(stock.get("currency"));
            if (currency == null) throw formatFailure();
            // An exact to arrives as to + 1ns (inclusive); millis drop that nanosecond again. RFC 3339 always has seconds.
            var rfc3339 = java.time.format.DateTimeFormatter.ISO_OFFSET_DATE_TIME;
            var range = new CompanyPriceResponse.Range(start.atZone(zone).format(rfc3339),
                    end.truncatedTo(java.time.temporal.ChronoUnit.MILLIS).atZone(zone).format(rfc3339), sessionDate);
            return CompanyPriceResponse.available(companyId, period,
                    new CompanyQuoteResponse.Source("toss", "토스증권", true, null, code, null), currency, interval, range, points);
        } catch (MarketDataException exception) {
            throw exception;
        } catch (TossUnsupportedSymbolException exception) {
            return CompanyPriceResponse.unavailable(companyId, period, "unsupported_symbol", "토스증권에서 이 종목을 찾지 못했어요.");
        } catch (RestClientException exception) {
            throw new MarketDataException(true);
        } catch (Exception exception) {
            throw new MarketDataException(false);
        }
    }

    record Session(String date, Instant open, Instant close) { }

    /**
     * The regular session for 1d, taken from Toss's market calendar (exchange-local date in, previous/current/next business
     * day out): the given day's session once it has opened, otherwise (before the open, a weekend or a holiday) the previous
     * business day's whole session. The calendar decides closures and early closes; missing bars never move the session.
     * KR is the calendar's integrated regular session, the union of KRX and NXT regular hours.
     * shortcut: that union equals KRX regular hours only while NXT's main market (09:00:30–15:20) stays inside KRX's; read a
     * KRX-only schedule if NXT ever trades outside KRX regular hours.
     * A day before today (exchange-local) is kept: its calendar no longer changes, while today's can still gain an early
     * close or a holiday. shortcut: per-process LRU of 256 market-days, shared store together with the minute cache.
     */
    private Session session(boolean krx, LocalDate day, Instant at, ZoneId zone) {
        String market = krx ? "KR" : "US";
        JsonNode calendar = calendarCache.get(market + "|" + day);
        if (calendar == null) {
            calendar = get("/api/v1/market-calendar/" + market, Map.of("date", day.toString())).path("result");
            // The calendar answers for the asked day; a missing or different date is a provider format failure, never a holiday.
            if (!day.toString().equals(text(calendar.path("today").get("date")))) throw formatFailure();
            if (day.isBefore(clock.instant().atZone(zone).toLocalDate())) calendarCache.put(market + "|" + day, calendar);
        }
        JsonNode today = calendar.path("today");
        Session current = regular(krx, today); // null: the asked day has no regular session (closed)
        // at is the exclusive end (an exact to + 1ns), so a to at the opening instant is in the session and gets its bucket.
        if (current != null && current.open().isBefore(at)) return current;
        Session previous = regular(krx, calendar.path("previousBusinessDay"));
        if (previous == null) throw formatFailure(); // a business day always has a regular session
        return previous;
    }

    /** A calendar day's regular session; null when the day has none (closed). */
    private static Session regular(boolean krx, JsonNode marketDay) {
        String date = text(marketDay.get("date"));
        JsonNode regular = (krx ? marketDay.path("integrated") : marketDay).path("regularMarket");
        if (date == null) throw formatFailure();
        if (regular.isMissingNode() || regular.isNull()) return null;
        Instant open = instant(text(regular.get("startTime"))), close = instant(text(regular.get("endTime")));
        if (open == null || close == null || !open.isBefore(close)) throw formatFailure();
        return new Session(date, open, close);
    }

    /** Minute bars over [start, end) in size-second buckets; every minute of the first and last bucket, so edge buckets are whole. */
    private List<CompanyPriceResponse.Point> minuteBuckets(String code, ZoneId zone, Instant start, Instant end, long size) {
        Instant first = Instant.ofEpochSecond(Math.floorDiv(start.getEpochSecond(), size) * size);
        Instant last = Instant.ofEpochSecond(Math.floorDiv(end.minusNanos(1).getEpochSecond(), size) * size + size);
        return PriceBars.byInterval(minuteBars(code, zone, first, last), size, zone);
    }

    /** Default range: one day, 7 days, one calendar month or one calendar year (KST) before the end. */
    public static Instant periodStart(String period, Instant end) {
        var at = end.atZone(KST);
        var start = switch (period) {
            case "1d" -> at.minusDays(1);
            case "1w" -> at.minusDays(7);
            case "1y" -> at.minusYears(1);
            default -> at.minusMonths(1);
        };
        return start.toInstant();
    }

    /**
     * 1-minute bars starting in [from, to), kept per exchange-local day. Days missing from the cache are read at the
     * same time, at most four at once across all requests, which keeps a cold 1w read under Toss's 20 requests a
     * second. A finished day is kept: Toss does not revise Korean candles, and US late trades only land in the first
     * hour after the day.
     * shortcut: per-process LRU of 512 symbol-days, move to a shared store once several API instances run.
     */
    private List<PriceBars.Bar> minuteBars(String code, ZoneId zone, Instant from, Instant to) {
        Instant settled = clock.instant().minus(java.time.Duration.ofHours(1));
        Map<LocalDate, java.util.concurrent.Future<List<PriceBars.Bar>>> reads = new java.util.LinkedHashMap<>();
        Map<LocalDate, List<PriceBars.Bar>> days = new java.util.HashMap<>();
        for (LocalDate day = from.atZone(zone).toLocalDate(); !day.isAfter(to.minusNanos(1).atZone(zone).toLocalDate());
                day = day.plusDays(1)) {
            List<PriceBars.Bar> cached = minuteCache.get(code + "|" + day);
            if (cached != null) { days.put(day, cached); continue; }
            Instant dayStart = day.atStartOfDay(zone).toInstant(), dayEnd = day.plusDays(1).atStartOfDay(zone).toInstant();
            reads.put(day, minuteReads.submit(() -> minuteDay(code, dayStart, dayEnd)));
        }
        try {
            for (var read : reads.entrySet()) {
                List<PriceBars.Bar> bars = read.getValue().get();
                days.put(read.getKey(), bars);
                if (!read.getKey().plusDays(1).atStartOfDay(zone).toInstant().isAfter(settled)) {
                    minuteCache.put(code + "|" + read.getKey(), bars);
                }
            }
        } catch (java.util.concurrent.ExecutionException exception) {
            reads.values().forEach(read -> read.cancel(true));
            if (exception.getCause() instanceof RuntimeException cause) throw cause;
            throw new MarketDataException(false);
        } catch (InterruptedException exception) {
            reads.values().forEach(read -> read.cancel(true));
            Thread.currentThread().interrupt();
            throw new MarketDataException(true);
        }
        List<PriceBars.Bar> bars = new java.util.ArrayList<>();
        days.values().forEach(dayBars -> dayBars.stream()
                .filter(bar -> !bar.start().isBefore(from) && bar.start().isBefore(to)).forEach(bars::add));
        return bars;
    }

    private final Map<String, List<PriceBars.Bar>> minuteCache = java.util.Collections.synchronizedMap(
            new java.util.LinkedHashMap<>(64, 0.75f, true) {
                @Override protected boolean removeEldestEntry(Map.Entry<String, List<PriceBars.Bar>> eldest) { return size() > 512; }
            });
    private final Map<String, JsonNode> calendarCache = java.util.Collections.synchronizedMap(
            new java.util.LinkedHashMap<>(16, 0.75f, true) {
                @Override protected boolean removeEldestEntry(Map.Entry<String, JsonNode> eldest) { return size() > 256; }
            });
    private final java.util.concurrent.ExecutorService minuteReads =
            java.util.concurrent.Executors.newFixedThreadPool(4, Thread.ofPlatform().daemon().name("toss-minute-", 0).factory());

    /** One day's 1-minute bars, walking back from the day's end; Toss stamps a 1-minute bar with its end time. */
    private List<PriceBars.Bar> minuteDay(String code, Instant dayStart, Instant dayEnd) {
        List<PriceBars.Bar> bars = new java.util.ArrayList<>();
        String before = dayEnd.toString();
        for (int page = 0; page < 20; page++) {
            JsonNode candlePage = get("/api/v1/candles", Map.of("symbol", code, "interval", "1m", "count", "200",
                    "before", before)).path("result");
            JsonNode candles = candlePage.path("candles");
            if (!candles.isArray()) throw formatFailure();
            Instant oldest = null;
            for (JsonNode candle : candles) {
                PriceBars.Bar bar = bar(candle, at -> at.minusSeconds(60));
                if (bar == null) continue;
                oldest = bar.start();
                if (!bar.start().isBefore(dayStart) && bar.start().isBefore(dayEnd)) bars.add(bar);
            }
            if (oldest == null || oldest.isBefore(dayStart) || !candlePage.hasNonNull("nextBefore")) break;
            before = text(candlePage.get("nextBefore"));
        }
        return bars;
    }

    /**
     * A candle as a bar starting at start(timestamp). Absent prices are no bar; a candle without a readable time or
     * with a present value of the wrong shape is a provider format failure (503), never skipped as missing data.
     */
    private static PriceBars.Bar bar(JsonNode candle, java.util.function.UnaryOperator<Instant> start) {
        String timestamp = strictText(candle.get("timestamp"));
        Instant at = timestamp == null ? null : instant(timestamp);
        if (at == null) throw formatFailure();
        Double open = strictNumber(candle.get("openPrice")), high = strictNumber(candle.get("highPrice"));
        Double low = strictNumber(candle.get("lowPrice")), close = strictNumber(candle.get("closePrice"));
        Double volume = strictNumber(candle.get("volume"));
        if (open == null || high == null || low == null || close == null) return null;
        return new PriceBars.Bar(start.apply(at), open, high, low, close, volume);
    }

    /** Daily candles newest first, following nextBefore for up to maxPages pages or until a page ends before stopBefore (KST day). */
    private List<JsonNode> dailyCandles(String code, int maxPages, Instant startBefore, Instant stopBefore) {
        List<JsonNode> daily = new java.util.ArrayList<>();
        // Starting at the requested end keeps an old range from falling off the page limit.
        String before = startBefore == null ? null : startBefore.toString();
        for (int page = 0; page < maxPages; page++) {
            var candleParams = new java.util.HashMap<String, Object>();
            candleParams.put("symbol", code); candleParams.put("interval", "1d"); candleParams.put("count", "200");
            if (before != null) candleParams.put("before", before);
            JsonNode candlePage = get("/api/v1/candles", candleParams).path("result");
            JsonNode candles = candlePage.path("candles");
            if (!candles.isArray()) throw formatFailure();
            candles.forEach(daily::add);
            if (candles.isEmpty() || !candlePage.hasNonNull("nextBefore")) break;
            Instant oldest = instant(text(candles.get(candles.size() - 1).get("timestamp")));
            if (stopBefore != null && oldest != null && oldest.isBefore(stopBefore)) break;
            before = text(candlePage.get("nextBefore"));
        }
        return daily;
    }

    /** Provider requests made and their total time, for the live check only. */
    final java.util.concurrent.atomic.AtomicLong requests = new java.util.concurrent.atomic.AtomicLong(), requestNanos = new java.util.concurrent.atomic.AtomicLong();

    private JsonNode get(String path, Map<String, ?> params) {
        long started = System.nanoTime();
        try {
            // A 429 means the 20-a-second bucket is empty; it refills within a second, so wait once and retry.
            for (int attempt = 0; ; attempt++) {
                try { return send(path, params); }
                catch (TossRateLimitedException exception) {
                    if (attempt == 2) throw new MarketDataException(true);
                    try { Thread.sleep(1000); }
                    catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); throw new MarketDataException(true); }
                }
            }
        } finally { requests.incrementAndGet(); requestNanos.addAndGet(System.nanoTime() - started); }
    }

    private JsonNode send(String path, Map<String, ?> params) {
        String accessToken = token();
        for (int attempt = 0; attempt < 2; attempt++) {
            final String usedToken = accessToken;
            final boolean firstAttempt = attempt == 0;
            var response = client.get().uri(uri -> {
                var builder = uri.path(path);
                // Values go through URI variables so reserved characters are encoded ("+09:00" -> "%2B09:00");
                // a literal "+" would otherwise reach the provider as a space.
                params.keySet().forEach(key -> builder.queryParam(key, "{" + key + "}"));
                return builder.build(params);
            }).header("Authorization", "Bearer " + usedToken).accept(MediaType.APPLICATION_JSON)
                    .exchange((request, result) -> {
                        int code = result.getStatusCode().value();
                        byte[] body = result.getBody().readAllBytes();
                        if (code == 401 && firstAttempt) return new HttpResult(code, body);
                        if (code == 401 || code == 403) throw new MarketDataException(false);
                        if (code == 400 || code == 404) throw new TossUnsupportedSymbolException();
                        if (code == 429) throw new TossRateLimitedException();
                        if (code >= 500) throw new MarketDataException(true);
                        if (code < 200 || code >= 300) throw new MarketDataException(false);
                        return new HttpResult(code, body);
                    });
            if (response.status == 401 && attempt == 0) { accessToken = token(usedToken); continue; }
            JsonNode root = read(response.body);
            if (!root.isObject() || !root.has("result")) throw formatFailure();
            return root;
        }
        throw new MarketDataException(false);
    }

    private String token() { return token(null); }
    private String token(String stale) {
        if (token != null && Instant.now().isBefore(tokenExpires) && !token.equals(stale)) return token;
        tokenLock.lock();
        try {
            if (token != null && Instant.now().isBefore(tokenExpires) && !token.equals(stale)) return token;
            var form = new LinkedMultiValueMap<String, String>();
            form.add("grant_type", "client_credentials");
            form.add("client_id", settings.tossClientId());
            form.add("client_secret", settings.tossClientSecret());
            JsonNode root;
            try {
                byte[] body = client.post().uri("/oauth2/token").contentType(MediaType.APPLICATION_FORM_URLENCODED)
                        .body(form).exchange((request, response) -> {
                            int code = response.getStatusCode().value();
                            byte[] bytes = response.getBody().readAllBytes();
                            if (code == 400 || code == 401 || code == 403) throw new TossAuthException();
                            if (code == 429 || code >= 500) throw new MarketDataException(true);
                            if (code < 200 || code >= 300) throw new MarketDataException(false);
                            return bytes;
                        });
                root = read(body);
            } catch (TossAuthException exception) { throw new MarketDataException(false); }
            catch (RestClientException exception) { throw new MarketDataException(true); }
            String newToken = text(root.get("access_token"));
            Double expires = number(root.get("expires_in"));
            if (newToken == null || expires == null || expires <= 0) throw formatFailure();
            token = newToken;
            long expiresSeconds = expires.longValue();
            tokenExpires = Instant.now().plusSeconds(Math.max(1, expiresSeconds - Math.min(60, expiresSeconds / 2)));
            return token;
        } finally { tokenLock.unlock(); }
    }

    private JsonNode read(byte[] bytes) {
        try { return mapper.readTree(bytes); }
        catch (Exception exception) { throw formatFailure(); }
    }
    private static JsonNode matching(JsonNode rows, String symbol) {
        if (rows == null || rows.isNull()) return null;
        if (!rows.isArray()) throw formatFailure();
        for (JsonNode row : rows) if (symbol.equalsIgnoreCase(text(row.get("symbol")))) return row;
        return null;
    }
    private static String text(JsonNode node) { return node == null || node.isNull() || !node.isString() ? null : node.stringValue(); }
    private static Double number(JsonNode node) {
        if (node == null || node.isNull()) return null;
        try { double value = node.isNumber() ? node.doubleValue() : node.isString() ? Double.parseDouble(node.stringValue()) : Double.NaN;
            return Double.isFinite(value) ? value : null; } catch (NumberFormatException ignored) { return null; }
    }
    private static java.time.ZoneId marketZone(String exchange) {
        return java.time.ZoneId.of("KRX".equals(exchange) ? "Asia/Seoul" : "America/New_York");
    }
    private static Double strictNumber(JsonNode node) {
        if (node == null || node.isNull()) return null;
        Double value = number(node);
        if (value == null) throw formatFailure();
        return value;
    }
    private static String strictText(JsonNode node) {
        if (node == null || node.isNull()) return null;
        if (!node.isString()) throw formatFailure();
        return node.stringValue().isBlank() ? null : node.stringValue();
    }
    private static Instant instant(String value) {
        if (value == null) return null;
        try { return java.time.OffsetDateTime.parse(value).toInstant(); }
        catch (Exception ignored) { try { return java.time.LocalDateTime.parse(value).atZone(java.time.ZoneId.of("Asia/Seoul")).toInstant(); }
            catch (Exception ignoredAgain) { return null; } }
    }
    private static boolean blank(String value) { return value == null || value.isBlank(); }
    private static MarketDataException formatFailure() { return new MarketDataException(false); }
    private record HttpResult(int status, byte[] body) { }
    private static class TossAuthException extends RuntimeException { }
    private static class TossUnsupportedSymbolException extends RuntimeException { }
    private static class TossRateLimitedException extends RuntimeException { }
}

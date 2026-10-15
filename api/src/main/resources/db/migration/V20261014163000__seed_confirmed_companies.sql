-- Seed the 24 confirmed companies without deleting historical catalog rows.
-- Existing document analyses may reference other company IDs.
INSERT INTO companies (id, name, ticker, exchange_code, aliases, brand_color) VALUES
    ('ORG:OPENAI', 'OpenAI', NULL, NULL, ARRAY[]::text[], NULL),
    ('ORG:ANTHROPIC', 'Anthropic', NULL, NULL, ARRAY[]::text[], NULL),
    ('NASDAQ:ASML', 'ASML', 'ASML', 'NASDAQ', ARRAY['ASML Holding']::text[], NULL),
    ('NYSE:TSM', 'TSMC', 'TSM', 'NYSE', ARRAY['Taiwan Semiconductor Manufacturing', 'Taiwan Semiconductor']::text[], NULL),
    ('KRX:005930', '삼성전자', '005930', 'KRX', ARRAY['Samsung Electronics', 'Samsung']::text[], '#1428A0'),
    ('NASDAQ:NVDA', 'NVIDIA', 'NVDA', 'NASDAQ', ARRAY['Nvidia', '엔비디아']::text[], '#76B900'),
    ('NASDAQ:AMD', 'AMD', 'AMD', 'NASDAQ', ARRAY['Advanced Micro Devices']::text[], '#ED1C24'),
    ('NASDAQ:AAPL', 'Apple', 'AAPL', 'NASDAQ', ARRAY['Apple, Inc.']::text[], '#000000'),
    ('KRX:000660', 'SK하이닉스', '000660', 'KRX', ARRAY['SK hynix', 'SK Hynix']::text[], NULL),
    ('NASDAQ:MU', 'Micron', 'MU', 'NASDAQ', ARRAY['Micron Technology']::text[], NULL),
    ('NASDAQ:MSFT', 'Microsoft', 'MSFT', 'NASDAQ', ARRAY['Microsoft Corporation']::text[], NULL),
    ('KRX:035420', '네이버', '035420', 'KRX', ARRAY['NAVER', 'Naver']::text[], '#03C75A'),
    ('KRX:035720', '카카오', '035720', 'KRX', ARRAY['Kakao']::text[], NULL),
    ('NASDAQ:META', 'Meta', 'META', 'NASDAQ', ARRAY['Meta Platforms', 'Meta Platforms, Inc.']::text[], '#0467DF'),
    ('NASDAQ:AMZN', 'Amazon', 'AMZN', 'NASDAQ', ARRAY['Amazon.com', 'Amazon.com, Inc.']::text[], '#FF9900'),
    ('KRX:064400', 'LG CNS', '064400', 'KRX', ARRAY['LG씨엔에스', '엘지씨엔에스']::text[], NULL),
    ('KRX:018260', '삼성SDS', '018260', 'KRX', ARRAY['삼성에스디에스', 'Samsung SDS']::text[], NULL),
    ('KRX:042700', '한미반도체', '042700', 'KRX', ARRAY['Hanmi Semiconductor']::text[], NULL),
    ('KRX:000990', 'DB하이텍', '000990', 'KRX', ARRAY['DB HiTek', 'DB Hitek']::text[], NULL),
    ('KRX:017670', 'SK텔레콤', '017670', 'KRX', ARRAY['SK Telecom', 'SKT']::text[], NULL),
    ('NASDAQ:GOOGL', 'Alphabet', 'GOOGL', 'NASDAQ', ARRAY['Google', '구글', '알파벳']::text[], '#4285F4'),
    ('NASDAQ:INTC', 'Intel', 'INTC', 'NASDAQ', ARRAY['Intel Corporation']::text[], '#0071C5'),
    ('NASDAQ:AVGO', 'Broadcom', 'AVGO', 'NASDAQ', ARRAY['Broadcom Inc.']::text[], '#E31837'),
    ('NASDAQ:ARM', 'Arm Holdings', 'ARM', 'NASDAQ', ARRAY['Arm', 'ARM']::text[], '#0091BD')
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    ticker = EXCLUDED.ticker,
    exchange_code = EXCLUDED.exchange_code,
    aliases = EXCLUDED.aliases,
    brand_color = EXCLUDED.brand_color
WHERE (companies.name, companies.ticker, companies.exchange_code, companies.aliases, companies.brand_color)
    IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.ticker, EXCLUDED.exchange_code, EXCLUDED.aliases, EXCLUDED.brand_color);

package com.zoop.chat.orchestrator;

import java.util.regex.Pattern;

/**
 * Whether a requirement's own words ask for a source outside ZOOP (web search design 1 and 2): ZOOP's documents alone do not
 * meet it, though the internal read still comes first. A fixed set of Korean expressions, read deterministically and never by
 * a model. Company names that are also search engines (구글, 네이버) do not count, and a request written against the web
 * ("웹 검색 말고") is no request for it.
 */
public final class ChatWebDemand {
    private static final Pattern WHITESPACE = Pattern.compile("\\s+");
    private static final Pattern EXTERNAL = Pattern.compile(
            "(외부(출처|자료|기사|보도|뉴스|소식|언론|매체)|외신|해외(언론|매체|보도|기사|뉴스)|언론(보도|기사)"
                    + "|웹(검색|에서)|인터넷(검색|에서))(?!.{0,6}(말고|없이|빼고|제외|않|마))");

    private ChatWebDemand() {
    }

    public static boolean asksExternalSource(String requirement) {
        return EXTERNAL.matcher(WHITESPACE.matcher(requirement).replaceAll("")).find();
    }
}

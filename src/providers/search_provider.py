import webbrowser
from urllib.parse import quote_plus


class SearchProvider:

    def open_search(self, provider, query):

        if provider == "github":

            url = (
                "https://github.com/search?q="
                + quote_plus(query)
            )

        else:

            url = (
                "https://duckduckgo.com/?q="
                + quote_plus(query)
            )

        webbrowser.open(url)

        return f"{provider} araması başlatıldı."
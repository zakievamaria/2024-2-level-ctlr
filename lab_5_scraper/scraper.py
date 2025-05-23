"""
Crawler implementation.
"""

# pylint: disable=too-many-arguments, too-many-instance-attributes, unused-import, undefined-variable, unused-argument
import datetime
import json
import math
import pathlib
import random
import shutil
import time
from typing import Pattern, Union

import requests
from bs4 import BeautifulSoup

from core_utils.article.article import Article
from core_utils.article.io import to_meta, to_raw
from core_utils.config_dto import ConfigDTO
from core_utils.constants import ASSETS_PATH, CRAWLER_CONFIG_PATH, PROJECT_ROOT


class IncorrectSeedURLError(Exception):
    """
    Exception raised when seed URL does not match standard pattern "https?://(www.)?".
    """


class NumberOfArticlesOutOfRangeError(Exception):
    """
    Exception raised when total number of articles is out of range from 1 to 150.
    """


class IncorrectNumberOfArticlesError(Exception):
    """
    Exception raised when total number of articles to parse is not integer or less than 0.
    """


class IncorrectHeadersError(Exception):
    """
    Exception raised when headers are not in a form of dictionary.
    """


class IncorrectEncodingError(Exception):
    """
    Exception raised when encoding is not specified as a string.
    """


class IncorrectTimeoutError(Exception):
    """
    Exception raised when timeout value is not a positive integer less than 60.
    """


class IncorrectVerifyError(Exception):
    """
    Exception raised when verify certificate value is not bool.
    """


class Config:
    """
    Class for unpacking and validating configurations.
    """

    def __init__(self, path_to_config: pathlib.Path) -> None:
        """
        Initialize an instance of the Config class.

        Args:
            path_to_config (pathlib.Path): Path to configuration.
        """
        self.path_to_config = path_to_config
        self.config = self._extract_config_content()
        self._seed_urls = self.config.seed_urls
        self._num_articles = self.config.total_articles
        self._headers = self.config.headers
        self._encoding = self.config.encoding
        self._timeout = self.config.timeout
        self._should_verify_certificate = self.config.should_verify_certificate
        self._headless_mode = self.config.headless_mode
        self._validate_config_content()

    def _extract_config_content(self) -> ConfigDTO:
        """
        Get config values.

        Returns:
            ConfigDTO: Config values
        """
        with open(self.path_to_config, 'r', encoding='utf-8') as file_to_read:
            scraper_config = json.load(file_to_read)
        return ConfigDTO(**scraper_config)

    def _validate_config_content(self) -> None:
        """
        Ensure configuration parameters are not corrupt.
        """
        if (not isinstance(self._seed_urls, list)
                or not all(isinstance(seed_url, str) for seed_url in self._seed_urls)
                or any('https://pravda-nn.ru/' not in seed_url for seed_url in self._seed_urls)):
            raise IncorrectSeedURLError('Seed URL does not match standard pattern.')

        if (not isinstance(self._num_articles, int) or isinstance(self._num_articles, bool)
                or self._num_articles <= 0):
            raise IncorrectNumberOfArticlesError('Number of articles is either not integer \
            or less than 0.')

        if self._num_articles not in range(1, 151):
            raise NumberOfArticlesOutOfRangeError('Number of articles is out of range.')

        if not isinstance(self._headers, dict):
            raise IncorrectHeadersError('Headers do not have a form of dictionary.')

        if not isinstance(self._encoding, str):
            raise IncorrectEncodingError('Encoding is not a string.')

        if (not isinstance(self._timeout, int) or isinstance(self._timeout, bool)
                or self._timeout not in range(1, 61)):
            raise IncorrectTimeoutError('Timeout is either not positive integer or more than 60.')

        if (not isinstance(self._should_verify_certificate, bool)
                or not isinstance(self._headless_mode, bool)):
            raise IncorrectVerifyError('Verify certificate value or headless mode value \
            are not bool.')

    def get_seed_urls(self) -> list[str]:
        """
        Retrieve seed urls.

        Returns:
            list[str]: Seed urls
        """
        return self._seed_urls

    def get_num_articles(self) -> int:
        """
        Retrieve total number of articles to scrape.

        Returns:
            int: Total number of articles to scrape
        """
        return self._num_articles

    def get_headers(self) -> dict[str, str]:
        """
        Retrieve headers to use during requesting.

        Returns:
            dict[str, str]: Headers
        """
        return self._headers

    def get_encoding(self) -> str:
        """
        Retrieve encoding to use during parsing.

        Returns:
            str: Encoding
        """
        return self._encoding

    def get_timeout(self) -> int:
        """
        Retrieve number of seconds to wait for response.

        Returns:
            int: Number of seconds to wait for response
        """
        return self._timeout

    def get_verify_certificate(self) -> bool:
        """
        Retrieve whether to verify certificate.

        Returns:
            bool: Whether to verify certificate or not
        """
        return self._should_verify_certificate

    def get_headless_mode(self) -> bool:
        """
        Retrieve whether to use headless mode.

        Returns:
            bool: Whether to use headless mode or not
        """
        return self._headless_mode


def make_request(url: str, config: Config) -> requests.models.Response:
    """
    Deliver a response from a request with given configuration.

    Args:
        url (str): Site url
        config (Config): Configuration

    Returns:
        requests.models.Response: A response from a request
    """
    a = random.randint(1, 3)
    time.sleep(a)
    response = requests.get(url=url, headers=config.get_headers(), timeout=config.get_timeout(),
                            verify=config.get_verify_certificate())
    requests.encoding = config.get_encoding()
    return response


class Crawler:
    """
    Crawler implementation.
    """

    #: Url pattern
    url_pattern: Union[Pattern, str]

    def __init__(self, config: Config) -> None:
        """
        Initialize an instance of the Crawler class.

        Args:
            config (Config): Configuration
        """
        self.config = config
        self.urls = []

    def _extract_url(self, article_bs: BeautifulSoup) -> str:
        """
        Find and retrieve url from HTML.

        Args:
            article_bs (bs4.BeautifulSoup): BeautifulSoup instance

        Returns:
            str: Url from HTML
        """
        url_for_extraction = article_bs.get('href')

        if not url_for_extraction.startswith('https://pravda-nn.ru/'):
            url_for_extraction = 'https://pravda-nn.ru/' + url_for_extraction

        if (url_for_extraction not in self.urls and isinstance(url_for_extraction, str)
                and not url_for_extraction.startswith('https://pravda-nn.ru/long/')):
            return url_for_extraction
        return ''

    def find_articles(self) -> None:
        """
        Find articles.
        """
        num_urls = math.ceil(self.config.get_num_articles() / len(self.config.get_seed_urls()))

        for seed_url in self.get_search_urls():
            response = make_request(seed_url, self.config)
            if not response.ok:
                continue

            bs = BeautifulSoup(response.content, 'html.parser')
            for article_bs in bs.find_all('a', class_=["content",
                                                       "article-news__wrapper nx-flex-col",
                                                       "nx-flex-row-btw"], href=True,
                                          limit=num_urls):
                extracted_url = self._extract_url(article_bs)

                if extracted_url == '':
                    continue
                self.urls.append(extracted_url)
                if len(self.urls) >= self.config.get_num_articles():
                    return

    def get_search_urls(self) -> list:
        """
        Get seed_urls param.

        Returns:
            list: seed_urls param
        """
        return self.config.get_seed_urls()


# 10
# 4, 6, 8, 10


class HTMLParser:
    """
    HTMLParser implementation.
    """

    def __init__(self, full_url: str, article_id: int, config: Config) -> None:
        """
        Initialize an instance of the HTMLParser class.

        Args:
            full_url (str): Site url
            article_id (int): Article id
            config (Config): Configuration
        """
        self.full_url = full_url
        self.article_id = article_id
        self.config = config
        self.article = Article(self.full_url, self.article_id)

    def _fill_article_with_text(self, article_soup: BeautifulSoup) -> None:
        """
        Find text of article.

        Args:
            article_soup (bs4.BeautifulSoup): BeautifulSoup instance
        """
        articles_text = article_soup.find_all(class_="article-content__wrapper")
        text = [
            p.text
            for article_text in articles_text
            for p in article_text.find_all(['p', 'li', 'h2'])
            if p.text.strip()
        ]
        self.article.text = '\n'.join(text)

    def _fill_article_with_meta_information(self, article_soup: BeautifulSoup) -> None:
        """
        Find meta information of article.

        Args:
            article_soup (bs4.BeautifulSoup): BeautifulSoup instance
        """
        self.article.article_id = self.article_id

        title = article_soup.find('meta', property="og:title").get('content')
        if not title:
            self.article.title = "NOT FOUND"
        if title and isinstance(title, str):
            self.article.title = title

        authors = article_soup.find(class_="author nx-flex-row-l-c")
        if authors is not None:
            self.article.author = [author.text for author in authors]
        if not self.article.author:
            self.article.author = ["NOT FOUND"]

        topics = article_soup.find(class_="articles-tags__wrapper nx-flex-row")
        if topics is None:
            self.article.topics = []
        else:
            self.article.topics = topics.get_text(separator=', ', strip=True).split(', ')

        date = article_soup.find(class_="date")
        if date is None:
            self.article.date = datetime.datetime.now()
        else:
            self.article.date = self.unify_date_format(date.get_text())

    def unify_date_format(self, date_str: str) -> datetime.datetime:
        """
        Unify date format.

        Args:
            date_str (str): Date in text format

        Returns:
            datetime.datetime: Datetime object
        """
        return datetime.datetime.strptime(date_str, '%H:%M, %d.%m.%Y')

    def parse(self) -> Union[Article, bool, list]:
        """
        Parse each article.

        Returns:
            Union[Article, bool, list]: Article instance
        """
        response = make_request(self.full_url, self.config)
        article_bs = BeautifulSoup(response.content, 'html.parser')
        self._fill_article_with_text(article_bs)
        self._fill_article_with_meta_information(article_bs)
        return self.article


class CrawlerRecursive(Crawler):
    """
    Find articles using recursive function.
    """
    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.start_url = 'https://pravda-nn.ru/'
        self.urls = [self.start_url]
        self.visited_urls = set()

    def find_articles(self) -> None:

        if len(self.urls) == 1:
            with open(PROJECT_ROOT / "lab_5_scraper" / "cash.json", "r",
                      encoding='utf-8') as file_to_read:
                data_urls = json.load(file_to_read)
            self.urls = data_urls['urls']
            self.visited_urls = set(data_urls['visited_urls'])

        for base_url in self.urls:
            if base_url in self.visited_urls:
                continue
            response = make_request(base_url, self.config)
            if not response.ok:
                continue
            bs = BeautifulSoup(response.content, 'html.parser')

            if base_url == self.start_url:
                for article_bs in bs.find_all('a',
                                              class_=["choice-title", "nx-flex-row-btw"],
                                              href=True):
                    extracted_url = self._extract_url(article_bs)
                    if extracted_url == '' or extracted_url in self.visited_urls:
                        continue
                    self.urls.append(extracted_url)
                    continue
            for article_bs in bs.find_all(class_=["article-news__wrapper nx-flex-col"]):
                a_href = article_bs.find_all('a')
                for href in a_href:
                    extracted_url = self._extract_url(href)
                    if extracted_url == '' or extracted_url in self.visited_urls:
                        continue
                    self.urls.append(extracted_url)

                if len(self.urls) - 1 >= self.config.get_num_articles():
                    self.urls.remove(self.start_url)
                    self.urls = self.urls[:self.config.get_num_articles()]
                    return

            self.visited_urls.add(base_url)

            with open(PROJECT_ROOT / "lab_5_scraper" / "cash.json", "r",
                      encoding='utf-8') as file_to_read:
                data_visited = json.load(file_to_read)
                data_visited.update({'urls': self.urls, 'visited_urls': list(self.visited_urls)})
            with open(PROJECT_ROOT / "lab_5_scraper" / "cash.json", 'w',
                      encoding='utf-8') as file_to_save:
                json.dump(data_visited, file_to_save, indent=4)

        if len(self.urls) - 1 < self.config.get_num_articles():
            self.find_articles()


def prepare_environment(base_path: Union[pathlib.Path, str]) -> None:
    """
    Create ASSETS_PATH folder if no created and remove existing folder.

    Args:
        base_path (Union[pathlib.Path, str]): Path where articles stores
    """
    if base_path.exists():
        shutil.rmtree(base_path)
    base_path.mkdir(parents=True, exist_ok=True)


def main() -> None:
    """
    Entrypoint for scrapper module.
    """
    configuration = Config(path_to_config=CRAWLER_CONFIG_PATH)
    prepare_environment(ASSETS_PATH)
    crawler = Crawler(config=configuration)
    crawler.find_articles()

    for i, full_url in enumerate(crawler.urls, 1):
        parser = HTMLParser(full_url=full_url, article_id=i, config=configuration)
        article = parser.parse()
        if isinstance(article, Article):
            to_raw(article)
            to_meta(article)


def main2() -> None:
    """
    Entrypoint for scrapper module.
    """
    configuration = Config(path_to_config=CRAWLER_CONFIG_PATH)
    prepare_environment(ASSETS_PATH)
    crawler_rec = CrawlerRecursive(config=configuration)

    if not pathlib.Path(PROJECT_ROOT / "lab_5_scraper" / "cash.json").exists():
        data = {'urls': crawler_rec.urls, 'visited_urls': []}
        with (open(PROJECT_ROOT / "lab_5_scraper" / "cash.json", 'w', encoding='utf-8')
              as file_to_save):
            json.dump(data, file_to_save, indent=4)

    crawler_rec.find_articles()

    for i, full_url in enumerate(crawler_rec.urls, 1):
        parser = HTMLParser(full_url=full_url, article_id=i, config=configuration)
        article = parser.parse()
        if isinstance(article, Article):
            to_raw(article)
            to_meta(article)
    print('finished')


if __name__ == "__main__":
    main()


# main2()

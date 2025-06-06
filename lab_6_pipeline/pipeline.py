"""
Pipeline for CONLL-U formatting.
"""

import glob

# pylint: disable=too-few-public-methods, undefined-variable, too-many-nested-blocks
import pathlib
from collections import Counter

import spacy_conll
import spacy_udpipe
from networkx import DiGraph

from core_utils.article.article import Article, ArtifactType
from core_utils.article.io import from_meta, from_raw, to_cleaned, to_meta
from core_utils.constants import ASSETS_PATH, PROJECT_ROOT
from core_utils.pipeline import (
    AbstractCoNLLUAnalyzer,
    CoNLLUDocument,
    LibraryWrapper,
    PipelineProtocol,
    StanzaDocument,
    TreeNode,
    UDPipeDocument,
    UnifiedCoNLLUDocument,
)
from core_utils.visualizer import visualize


class EmptyDirectoryError(Exception):
    """
    Exception raised when directory does not contain any files.
    """


class InconsistentDatasetError(Exception):
    """
    Exception raised when IDs contain slips, number of meta
    and raw files is not equal, files are empty.
    """


class EmptyFileError(Exception):
    """
    Exception raised when an article file is empty.
    """


class CorpusManager:
    """
    Work with articles and store them.
    """

    def __init__(self, path_to_raw_txt_data: pathlib.Path) -> None:
        """
        Initialize an instance of the CorpusManager class.

        Args:
            path_to_raw_txt_data (pathlib.Path): Path to raw txt data
        """
        self.path = path_to_raw_txt_data
        self._validate_dataset()
        self._storage = {}
        self._scan_dataset()

    def _validate_dataset(self) -> None:
        """
        Validate folder with assets.
        """
        if not self.path.exists():
            raise FileNotFoundError('File with articles does not exist.')

        if not self.path.is_dir():
            raise NotADirectoryError('The path does not lead to a directory.')

        if not any(self.path.iterdir()):
            raise EmptyDirectoryError('This directory is empty.')

        raw_names = [raw.name for raw in self.path.iterdir() if 'raw' in raw.name]
        raw_names.sort()
        meta_names = [meta.name for meta in self.path.iterdir() if 'meta' in meta.name]
        meta_names.sort()

        if len(raw_names) != len(meta_names):
            raise InconsistentDatasetError('Number of meta and raw files is not equal.')

        if any(True for filepath in self.path.iterdir()
               if filepath.stat().st_size == 0 and
                  ('raw' in filepath.name or 'meta' in filepath.name)):
            raise InconsistentDatasetError('The file is empty.')

        raw_check = [f"{i}_raw.txt" for i in range(1, len(raw_names) + 1)]
        raw_check.sort()
        meta_check = [f"{i}_meta.json" for i in range(1, len(meta_names) + 1)]
        meta_check.sort()

        if (any(True for raw_name in zip(raw_names, raw_check) if raw_name[0] != raw_name[1]) or
                any(True for meta_name in zip(meta_names, meta_check)
                    if meta_name[0] != meta_name[1])):
            raise InconsistentDatasetError('IDs contain slips.')

    def _scan_dataset(self) -> None:
        """
        Register each dataset entry.
        """
        for file in glob.glob(str(self.path / '*raw*')):
            article_from_raw = from_raw(file)
            self._storage[article_from_raw.article_id] = article_from_raw

    def get_articles(self) -> dict:
        """
        Get storage params.

        Returns:
            dict: Storage params
        """
        return dict(sorted(self._storage.items()))


class TextProcessingPipeline(PipelineProtocol):
    """
    Preprocess and morphologically annotate sentences into the CONLL-U format.
    """

    def __init__(
        self, corpus_manager: CorpusManager, analyzer: LibraryWrapper | None = None
    ) -> None:
        """
        Initialize an instance of the TextProcessingPipeline class.

        Args:
            corpus_manager (CorpusManager): CorpusManager instance
            analyzer (LibraryWrapper | None): Analyzer instance
        """
        self._corpus = corpus_manager
        self._analyzer = analyzer

    def run(self) -> None:
        """
        Perform basic preprocessing and write processed text to files.
        """
        for article in self._corpus.get_articles().values():
            to_cleaned(article)
        analyzed_texts = self._analyzer.analyze([text.text for text
                                                 in list(self._corpus.get_articles().values())])
        for article_id, conllu_article in self._corpus.get_articles().items():
            conllu_article.set_conllu_info(analyzed_texts[article_id - 1])
            self._analyzer.to_conllu(conllu_article)


class UDPipeAnalyzer(LibraryWrapper):
    """
    Wrapper for udpipe library.
    """

    #: Analyzer
    _analyzer: AbstractCoNLLUAnalyzer

    def __init__(self) -> None:
        """
        Initialize an instance of the UDPipeAnalyzer class.
        """
        self._analyzer = self._bootstrap()

    def _bootstrap(self) -> AbstractCoNLLUAnalyzer:
        """
        Load and set up the UDPipe model.

        Returns:
            AbstractCoNLLUAnalyzer: Analyzer instance
        """
        model = spacy_udpipe.load_from_path(lang="ru",
                                            path=str(PROJECT_ROOT / "lab_6_pipeline" / "assets" /
                                                     "model" /
                                                     "russian-syntagrus-ud-2.0-170801.udpipe"))
        model.add_pipe(
            "conll_formatter",
            last=True,
            config={"conversion_maps": {"XPOS": {"": "_"}}, "include_headers": True},
        )
        return model

    def analyze(self, texts: list[str]) -> list[UDPipeDocument | str]:
        """
        Process texts into CoNLL-U formatted markup.

        Args:
            texts (list[str]): Collection of texts

        Returns:
            list[UDPipeDocument | str]: List of documents
        """
        return [self._analyzer(text)._.conll_str for text in texts]

    def to_conllu(self, article: Article) -> None:
        """
        Save content to ConLLU format.

        Args:
            article (Article): Article containing information to save
        """
        with (open(article.get_file_path(ArtifactType.UDPIPE_CONLLU), "w", encoding="utf-8")
              as annotation_file):
            annotation_file.write(article.get_conllu_info())
            annotation_file.write("\n")

    def from_conllu(self, article: Article) -> UDPipeDocument:
        """
        Load ConLLU content from article stored on disk.

        Args:
            article (Article): Article to load

        Returns:
            UDPipeDocument: Document ready for parsing
        """
        conllu_parser = spacy_conll.parser.ConllParser(self._analyzer)
        path_to_conllu = article.get_file_path(ArtifactType.UDPIPE_CONLLU)
        if path_to_conllu.stat().st_size == 0:
            raise EmptyFileError('The file is empty.')
        with open(path_to_conllu, 'r', encoding='utf-8') as conllu_to_read:
            conllu_to_parse = conllu_to_read.read()
        parsed_doc: UDPipeDocument = (conllu_parser.parse_conll_text_as_spacy
                                      (conllu_to_parse.strip('\n')))
        return parsed_doc

    def get_document(self, doc: UDPipeDocument) -> UnifiedCoNLLUDocument:
        """
        Present ConLLU document's sentence tokens as a unified structure.

        Args:
            doc (UDPipeDocument): ConLLU document

        Returns:
            UnifiedCoNLLUDocument: Dictionary of token features within document sentences
        """


class StanzaAnalyzer(LibraryWrapper):
    """
    Wrapper for stanza library.
    """

    #: Analyzer
    _analyzer: AbstractCoNLLUAnalyzer

    def __init__(self) -> None:
        """
        Initialize an instance of the StanzaAnalyzer class.
        """

    def _bootstrap(self) -> AbstractCoNLLUAnalyzer:
        """
        Load and set up the Stanza model.

        Returns:
            AbstractCoNLLUAnalyzer: Analyzer instance
        """

    def analyze(self, texts: list[str]) -> list[StanzaDocument]:
        """
        Process texts into CoNLL-U formatted markup.

        Args:
            texts (list[str]): Collection of texts

        Returns:
            list[StanzaDocument]: List of documents
        """

    def to_conllu(self, article: Article) -> None:
        """
        Save content to ConLLU format.

        Args:
            article (Article): Article containing information to save
        """

    def from_conllu(self, article: Article) -> StanzaDocument:
        """
        Load ConLLU content from article stored on disk.

        Args:
            article (Article): Article to load

        Returns:
            StanzaDocument: Document ready for parsing
        """

    def get_document(self, doc: StanzaDocument) -> UnifiedCoNLLUDocument:
        """
        Present ConLLU document's sentence tokens as a unified structure.

        Args:
            doc (StanzaDocument): ConLLU document

        Returns:
            UnifiedCoNLLUDocument: Document of token features within document sentences
        """


class POSFrequencyPipeline:
    """
    Count frequencies of each POS in articles, update meta info and produce graphic report.
    """

    def __init__(self, corpus_manager: CorpusManager, analyzer: LibraryWrapper) -> None:
        """
        Initialize an instance of the POSFrequencyPipeline class.

        Args:
            corpus_manager (CorpusManager): CorpusManager instance
            analyzer (LibraryWrapper): Analyzer instance
        """
        self._corpus = corpus_manager
        self._analyzer = analyzer

    def _count_frequencies(self, article: Article) -> dict[str, int]:
        """
        Count POS frequency in Article.

        Args:
            article (Article): Article instance

        Returns:
            dict[str, int]: POS frequencies
        """
        ud_info = self._analyzer.from_conllu(article)
        pos = [get_pos.pos_ for get_pos in ud_info]
        return dict(Counter(pos))

    def run(self) -> None:
        """
        Visualize the frequencies of each part of speech.
        """
        for article_to_vis in self._corpus.get_articles().values():
            from_meta(article_to_vis.get_meta_file_path(), article_to_vis)
            pos_freq = self._count_frequencies(article_to_vis)
            article_to_vis.set_pos_info(pos_freq)
            to_meta(article_to_vis)
            visualize(article=article_to_vis,
                      path_to_save=ASSETS_PATH / f'{article_to_vis.article_id}_image.png')


class PatternSearchPipeline(PipelineProtocol):
    """
    Search for the required syntactic pattern.
    """

    def __init__(
        self, corpus_manager: CorpusManager, analyzer: LibraryWrapper, pos: tuple[str, ...]
    ) -> None:
        """
        Initialize an instance of the PatternSearchPipeline class.

        Args:
            corpus_manager (CorpusManager): CorpusManager instance
            analyzer (LibraryWrapper): Analyzer instance
            pos (tuple[str, ...]): Root, Dependency, Child part of speech
        """
        self._corpus = corpus_manager
        self._analyzer = analyzer
        self._node_labels = pos

    def _make_graphs(self, doc: CoNLLUDocument) -> list[DiGraph]:
        """
        Make graphs for a document.

        Args:
            doc (CoNLLUDocument): Document for patterns searching

        Returns:
            list[DiGraph]: Graphs for the sentences in the document
        """
        graphs = []
        for sent in doc.sents:
            digraph = DiGraph()
            for token in sent:
                digraph.add_node(token.id, label=token.upos)
            for token in sent:
                if token.head == '0':
                    continue
                digraph.add_edge(int(token.head), token.id, label=token.deprel)
            graphs.append(digraph)
        return graphs

    def _add_children(
        self, graph: DiGraph, subgraph_to_graph: dict, node_id: int, tree_node: TreeNode
    ) -> None:
        """
        Add children to TreeNode.

        Args:
            graph (DiGraph): Sentence graph to search for a pattern
            subgraph_to_graph (dict): Matched subgraph
            node_id (int): ID of root node of the match
            tree_node (TreeNode): Root node of the match
        """

    def _find_pattern(self, doc_graphs: list) -> dict[int, list[TreeNode]]:
        """
        Search for the required pattern.

        Args:
            doc_graphs (list): A list of graphs for the document

        Returns:
            dict[int, list[TreeNode]]: A dictionary with pattern matches
        """

    def run(self) -> None:
        """
        Search for a pattern in documents and writes found information to JSON file.
        """


def main() -> None:
    """
    Entrypoint for pipeline module.
    """
    corpus_manager = CorpusManager(path_to_raw_txt_data=ASSETS_PATH)
    udpipe_analyzer = UDPipeAnalyzer()
    pipeline = TextProcessingPipeline(corpus_manager, udpipe_analyzer)
    pipeline.run()
    visualizer_pos_fr = POSFrequencyPipeline(corpus_manager, udpipe_analyzer)
    visualizer_pos_fr.run()


if __name__ == "__main__":
    main()

from typing import Iterator, List, Tuple

import spacy
from datasets import Dataset
from spacy.tokens import Doc

from zshot import Linker, MentionsExtractor, PipelineConfig
from zshot.evaluation.dataset.dataset import DatasetWithRelations
from zshot.evaluation.dataset.fewrel.fewrel import get_few_rel_data
from zshot.evaluation.evaluator import (
    MentionsExtractorEvaluator,
    RelationExtractorEvaluator,
    ZeroShotTokenClassificationEvaluator,
)
from zshot.evaluation.metrics.rel_eval import RelEval
from zshot.evaluation.pipeline import (
    LinkerPipeline,
    MentionsExtractorPipeline,
    RelationExtractorPipeline,
)
from zshot.relation_extractor.relation_extractor_zsrc import RelationsExtractorZSRC
from zshot.utils.alignment_utils import AlignmentMode
from zshot.utils.data_models import Entity, Span

ENTITIES = [
    Entity(name="FAC", description="A facility"),
    Entity(name="LOC", description="A location"),
]


class DummyLinker(Linker):
    def __init__(self, predictions: List[Tuple[str, str, float]]):
        super().__init__()
        self.predictions = predictions

    def predict(self, docs: Iterator[Doc], batch_size=None):
        sentences = []
        for doc in docs:
            preds = []
            for span, label, score in self.predictions:
                if span in doc.text:
                    preds.append(
                        Span(
                            doc.text.find(span),
                            doc.text.find(span) + len(span),
                            label=label,
                            score=score,
                        )
                    )
            sentences.append(preds)

        return sentences


class DummyLinkerEnd2EndForEval(Linker):
    @property
    def is_end2end(self) -> bool:
        return True

    def __init__(self, predictions):
        # this dummy linker works correctly ONLY if no shuffling is done by spacy when batching documents
        super().__init__()
        self.predictions = predictions
        self.curr_idx = 0

    def predict(self, docs, batch_size=100):
        rval = []
        for _ in docs:
            rval.append(
                [Span(item["start"], item["end"], item["label"]) for item in self.predictions[self.curr_idx]]
            )
            self.curr_idx += 1
        return rval


class DummyMentionsExtractor(MentionsExtractor):
    def __init__(self, predictions: List[Tuple[str, str, float]]):
        super().__init__()
        self.predictions = predictions

    def predict(self, docs: Iterator[Doc], batch_size=None):
        sentences = []
        for doc in docs:
            preds = []
            for span, label, score in self.predictions:
                if span in doc.text:
                    preds.append(
                        Span(
                            doc.text.find(span),
                            doc.text.find(span) + len(span),
                            label="MENTION",
                            score=score,
                        )
                    )
            sentences.append(preds)

        return sentences


def get_linker_pipe(predictions: List[Tuple[str, str, float]]):
    nlp = spacy.blank("en")
    nlp_config = PipelineConfig(linker=DummyLinker(predictions), entities=ENTITIES)

    nlp.add_pipe("zshot", config=nlp_config, last=True)

    return LinkerPipeline(nlp)


def get_mentions_extractor_pipe(predictions: List[Tuple[str, str, float]]):
    nlp = spacy.blank("en")
    nlp_config = PipelineConfig(
        mentions_extractor=DummyMentionsExtractor(predictions), entities=ENTITIES
    )

    nlp.add_pipe("zshot", config=nlp_config, last=True)

    return MentionsExtractorPipeline(nlp)


def get_relation_extraction_pipeline(dataset: DatasetWithRelations):

    nlp = spacy.blank("en")
    nlp_config = PipelineConfig(
        relations_extractor=RelationsExtractorZSRC(thr=0.0),
        linker=DummyLinkerEnd2EndForEval(dataset["sentence_entities"]),
        relations=dataset.relations,
    )
    nlp.add_pipe("zshot", config=nlp_config, last=True)
    return RelationExtractorPipeline(nlp)


def get_spans_predictions(span: str, label: str, sentence: str):
    return [
        {
            "start": sentence.find(span),
            "end": sentence.find(span) + len(span),
            "entity": label,
            "score": 1,
        }
    ]


def get_dataset(gt: List[List[str]], sentence: List[str]):
    data_dict = {
        "tokens": [s.split(" ") for s in sentence],
        "ner_tags": gt,
    }
    dataset = Dataset.from_dict(data_dict)
    dataset.entities = ENTITIES
    return dataset


class TestZeroShotTokenClassificationEvaluation:
    def test_preprocess(self):
        sentences = ["New York is beautiful"]
        gt = [["B-FAC", "I-FAC", "O", "O"]]

        predictions = [get_spans_predictions("New York", "FAC", sentences[0])]
        custom_evaluator = ZeroShotTokenClassificationEvaluator("token-classification")

        preds = custom_evaluator.predictions_processor(
            predictions, [["New", "York", "is", "beautiful"]], join_by=" "
        )
        assert preds["predictions"] == gt

    def test_prediction_token_based_evaluation_all_matching(self):
        sentences = ["New York is beautiful"]
        gt = [["B-FAC", "I-FAC", "O", "O"]]

        dataset = get_dataset(gt, sentences)

        custom_evaluator = ZeroShotTokenClassificationEvaluator("token-classification")
        metrics = custom_evaluator.compute(
            get_linker_pipe([("New York", "FAC", 1)]), dataset, metric="seqeval"
        )

        assert float(metrics["overall_precision"]) == 1.0
        assert float(metrics["overall_precision"]) == 1.0
        assert float(metrics["overall_f1"]) == 1.0
        assert float(metrics["overall_accuracy"]) == 1.0

    def test_prediction_token_based_evaluation_overlapping_spans(self):
        sentences = ["New York is beautiful"]
        gt = [["B-FAC", "I-FAC", "O", "O"]]

        dataset = get_dataset(gt, sentences)

        custom_evaluator = ZeroShotTokenClassificationEvaluator("token-classification")
        metrics = custom_evaluator.compute(
            get_linker_pipe([("New York", "FAC", 1), ("York", "LOC", 0.7)]),
            dataset,
            metric="seqeval",
        )

        assert float(metrics["overall_precision"]) == 1.0
        assert float(metrics["overall_precision"]) == 1.0
        assert float(metrics["overall_f1"]) == 1.0
        assert float(metrics["overall_accuracy"]) == 1.0

    def test_prediction_token_based_evaluation_partial_match_spans_expand(self):
        sentences = ["New York is beautiful"]
        gt = [["B-FAC", "I-FAC", "O", "O"]]

        dataset = get_dataset(gt, sentences)

        custom_evaluator = ZeroShotTokenClassificationEvaluator(
            "token-classification", alignment_mode=AlignmentMode.expand
        )
        pipe = get_linker_pipe([("New Yo", "FAC", 1)])
        metrics = custom_evaluator.compute(pipe, dataset, metric="seqeval")

        assert float(metrics["overall_precision"]) == 1.0
        assert float(metrics["overall_precision"]) == 1.0
        assert float(metrics["overall_f1"]) == 1.0
        assert float(metrics["overall_accuracy"]) == 1.0

    def test_prediction_token_based_evaluation_partial_match_spans_contract(self):
        sentences = ["New York is beautiful"]
        gt = [["B-FAC", "I-FAC", "O", "O"]]

        dataset = get_dataset(gt, sentences)

        custom_evaluator = ZeroShotTokenClassificationEvaluator(
            "token-classification", alignment_mode=AlignmentMode.contract
        )
        pipe = get_linker_pipe([("New York i", "FAC", 1)])
        metrics = custom_evaluator.compute(pipe, dataset, metric="seqeval")

        assert float(metrics["overall_precision"]) == 1.0
        assert float(metrics["overall_precision"]) == 1.0
        assert float(metrics["overall_f1"]) == 1.0
        assert float(metrics["overall_accuracy"]) == 1.0

    def test_prediction_token_based_evaluation_partial_and_overlapping_spans(self):
        sentences = ["New York is beautiful"]
        gt = [["B-FAC", "I-FAC", "O", "O"]]

        dataset = get_dataset(gt, sentences)

        custom_evaluator = ZeroShotTokenClassificationEvaluator(
            "token-classification", alignment_mode=AlignmentMode.contract
        )
        pipe = get_linker_pipe([("New York i", "FAC", 1), ("w York", "LOC", 0.7)])
        metrics = custom_evaluator.compute(pipe, dataset, metric="seqeval")

        assert float(metrics["overall_precision"]) == 1.0
        assert float(metrics["overall_precision"]) == 1.0
        assert float(metrics["overall_f1"]) == 1.0
        assert float(metrics["overall_accuracy"]) == 1.0


class TestMentionsExtractorEvaluator:
    def test_prepare_data(self):
        sentences = ["New York is beautiful"]
        gt = [["B-FAC", "I-FAC", "O", "O"]]
        processed_gt = [["B-MENTION", "I-MENTION", "O", "O"]]

        dataset = get_dataset(gt, sentences)

        custom_evaluator = MentionsExtractorEvaluator("token-classification")

        preds = custom_evaluator.prepare_data(
            dataset, input_column="tokens", label_column="ner_tags", join_by=" "
        )
        assert preds[0]["references"] == processed_gt

    def test_prediction_token_based_evaluation_all_matching(self):
        sentences = ["New York is beautiful"]
        gt = [["B-FAC", "I-FAC", "O", "O"]]

        dataset = get_dataset(gt, sentences)

        custom_evaluator = MentionsExtractorEvaluator("token-classification")
        metrics = custom_evaluator.compute(
            get_mentions_extractor_pipe([("New York", "FAC", 1)]),
            dataset,
            metric="seqeval",
        )

        assert float(metrics["overall_precision"]) == 1.0
        assert float(metrics["overall_precision"]) == 1.0
        assert float(metrics["overall_f1"]) == 1.0
        assert float(metrics["overall_accuracy"]) == 1.0

    def test_prediction_token_based_evaluation_overlapping_spans(self):
        sentences = ["New York is beautiful"]
        gt = [["B-FAC", "I-FAC", "O", "O"]]

        dataset = get_dataset(gt, sentences)

        custom_evaluator = MentionsExtractorEvaluator("token-classification")
        metrics = custom_evaluator.compute(
            get_mentions_extractor_pipe([("New York", "FAC", 1), ("York", "LOC", 0.7)]),
            dataset,
            metric="seqeval",
        )

        assert float(metrics["overall_precision"]) == 1.0
        assert float(metrics["overall_precision"]) == 1.0
        assert float(metrics["overall_f1"]) == 1.0
        assert float(metrics["overall_accuracy"]) == 1.0

    def test_prediction_token_based_evaluation_partial_match_spans_expand(self):
        sentences = ["New York is beautiful"]
        gt = [["B-FAC", "I-FAC", "O", "O"]]

        dataset = get_dataset(gt, sentences)

        custom_evaluator = MentionsExtractorEvaluator(
            "token-classification", alignment_mode=AlignmentMode.expand
        )
        pipe = get_mentions_extractor_pipe([("New Yo", "FAC", 1)])
        metrics = custom_evaluator.compute(pipe, dataset, metric="seqeval")

        assert float(metrics["overall_precision"]) == 1.0
        assert float(metrics["overall_precision"]) == 1.0
        assert float(metrics["overall_f1"]) == 1.0
        assert float(metrics["overall_accuracy"]) == 1.0


class TestZeroShotTextClassificationEvaluation:

    def test_relation_classification_prediction(self):
        dataset = get_few_rel_data(split_name="val_wiki[0:5]")

        custom_evaluator = RelationExtractorEvaluator()
        pipe = get_relation_extraction_pipeline(dataset)
        results = custom_evaluator.compute(
            pipe,
            dataset,
            input_column="sentences",
            label_column="labels",
            metric=RelEval(),
        )
        assert len(dataset) == 5
        assert results is not None

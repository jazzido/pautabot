import dataclasses
from datetime import datetime
import logging
import os
import pickle
from typing import Dict, List, Optional, Set, Tuple
import sys

import dotenv
from dataclasses_json import dataclass_json
import requests
import tweepy

STATE_FILE = "pautabot.state"
BIGNUM = 9e15
CURRENT_YEAR = datetime.now().year
KEYWORD_TO_CHECK = "publicidad"

AD_PURCHASES_URL = f"https://gobiernoabierto.bahia.gob.ar/WS/2328/{CURRENT_YEAR}"
ALL_PURCHASES_URL = f"https://gobiernoabierto.bahia.gob.ar/WS/2307/{CURRENT_YEAR}"
DETAIL_PURCHASE_URL_TEMPLATE = (
    "https://gobiernoabierto.bahia.gob.ar/WS/2312/{year}/{ordencompra}"
)
DETAIL_PURCHASE_PAGE_URL_TEMPLATE = (
    "https://www.bahia.gob.ar/compras/data/oc/{year}/{ordencompra}"
)

TWEET_TEMPLATE = """
💸 Nuevo gasto de pauta oficial:

📰  Proveedor: {proveedor}
🏛  Dependencia: {dependencia}
🗓  Fecha: {fecha}
💵  Importe: $ {importe}

{url}
"""

BOLD_TRANS = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!?.,\"'",
    "𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗❗❓.,\"'",
)

DIGIT_TRANS = str.maketrans("1234567890", "𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵𝟬")


def boldify(s: str) -> str:
    """
    >>> boldify("Gran inversion, 65 palos para adornar periodistas")
    '𝐆𝐫𝐚𝐧 𝐢𝐧𝐯𝐞𝐫𝐬𝐢𝐨𝐧, 𝟔𝟓 𝐩𝐚𝐥𝐨𝐬 𝐩𝐚𝐫𝐚 𝐚𝐝𝐨𝐫𝐧𝐚𝐫 𝐩𝐞𝐫𝐢𝐨𝐝𝐢𝐬𝐭𝐚𝐬'
    """
    return s.translate(BOLD_TRANS)


def monodigits(s: str) -> str:
    return s.translate(DIGIT_TRANS)


@dataclass_json
@dataclasses.dataclass
class Purchase:
    ejercicio: int
    ordencompra: int
    fecha: str
    importe: float
    proveedor: str
    dependencia: str
    expediente: str


@dataclasses.dataclass
class ProcessedPurchase(Purchase):
    processed_at: datetime
    status: str  # one of: "processed", "dropped"
    tweet_id: Optional[str]


@dataclasses.dataclass
class RunState:
    last_run: datetime
    totals_by_seller: Dict[str, float]
    all_purchases: List[Purchase]
    processed_purchases: List[ProcessedPurchase]


logger = logging.getLogger("pautabot")
log_handler = logging.StreamHandler(sys.stdout)
log_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
if logger.hasHandlers():
    logger.handlers.clear()
logger.addHandler(log_handler)
logger.setLevel(logging.DEBUG)


def init_twitter_client() -> tweepy.API:
    auth = tweepy.OAuthHandler(
        os.environ["TWITTER_API_KEY"], os.environ["TWITTER_SECRET_KEY"]
    )
    auth.set_access_token(
        os.environ["TWITTER_ACCESS_TOKEN"], os.environ["TWITTER_TOKEN_SECRET"]
    )
    api = tweepy.API(auth, wait_on_rate_limit=True, wait_on_rate_limit_notify=True)
    api.verify_credentials()

    return api


def purchase_detail_url(purchase: Purchase) -> str:
    return DETAIL_PURCHASE_URL_TEMPLATE.format(
        year=purchase.ejercicio, ordencompra=purchase.ordencompra
    )


def get_advertisement_totals_by_seller() -> Dict[str, float]:
    resp = requests.get(AD_PURCHASES_URL)
    return {row["proveedor"]: float(row["monto"]) for row in resp.json()}


def get_all_purchases() -> List[Purchase]:
    resp = requests.get(ALL_PURCHASES_URL)
    all_purchases = Purchase.schema().load(resp.json(), many=True)
    return sorted(
        all_purchases,
        key=lambda p: datetime.strptime(p.fecha, "%d-%m-%Y"),
        reverse=True,
    )


def diff_totals(old: Dict[str, float], new: Dict[str, float]) -> List[str]:
    """
    >>> diff_totals({"foo": 10, "bar": 20}, {"foo": 20, "bar": 20})
    ['foo']

    >>> diff_totals({"quux": 10}, {"foo": 20, "bar": 20})
    ['foo', 'bar']

    >>> diff_totals({"foo": 10, "bar": 10}, {"foo": 20, "bar": 20})
    ['foo', 'bar']

    >>> diff_totals({"foo": 10, "bar": 20}, {"quux": 20})
    ['quux']
    """

    sellers_to_process = [
        new_seller
        for new_seller, new_amount in new.items()
        if old.get(new_seller, BIGNUM) < new_amount or new_seller not in old
    ]

    return sellers_to_process


def get_purchase_detail(url: str) -> List[dict]:
    resp = requests.get(url)
    return resp.json()


def get_unprocessed_purchases_for_seller(
    all_purchases: List, processed_purchases: List[ProcessedPurchase], seller: str
) -> List[Purchase]:
    processed_purchases_set: Set[Tuple[int, int]] = set()
    for pp in processed_purchases:
        processed_purchases_set.add((pp.ejercicio, pp.ordencompra))

    unprocessed_purchases = [
        purchase
        for purchase in all_purchases
        if purchase.proveedor == seller
        and (purchase.ejercicio, purchase.ordencompra) not in processed_purchases_set
    ]

    return unprocessed_purchases


def tweet_new_purchase(purchase: Purchase, twitter_client: tweepy.API) -> tweepy.Status:
    tweet_body = TWEET_TEMPLATE.format(
        fecha=purchase.fecha,
        proveedor=purchase.proveedor,
        dependencia=purchase.dependencia,
        importe="{:,}".format(int(purchase.importe)).replace(",", "."),
        url=DETAIL_PURCHASE_PAGE_URL_TEMPLATE.format(
            year=purchase.ejercicio, ordencompra=purchase.ordencompra
        ),
    )

    status = twitter_client.update_status(tweet_body)

    return status


def _save_state(state: RunState):
    logger.info("Saving new state")
    with open(STATE_FILE, "wb") as sf:
        pickle.dump(state, sf)


def main():
    logger.info(f"Running {__name__}")
    with open(STATE_FILE, "rb") as sf:
        state: RunState = pickle.load(sf)

    logger.info(
        (
            "Read state. last_run: %s - "
            "len(totals_by_seller): %d - len(all_purchases): %d - "
            "len(processed_purchases): %d"
        ),
        state.last_run,
        len(state.totals_by_seller),
        len(state.all_purchases),
        len(state.processed_purchases),
    )
    state.last_run = datetime.now()

    logger.info("Getting all purchases")
    state.all_purchases = get_all_purchases()
    logger.info("Getting ad purchases")
    ad_purchases_totals = get_advertisement_totals_by_seller()

    # Get sellers to find new purchases
    sellers_to_process = diff_totals(state.totals_by_seller, ad_purchases_totals)
    state.totals_by_seller = ad_purchases_totals

    if len(sellers_to_process) == 0:
        logger.info("No changes since %s - Bye.", state.last_run)
        _save_state(state)
        sys.exit(0)
    else:
        twitter_client = init_twitter_client()
        tweet_queue: List[Purchase] = []

    for seller in sellers_to_process:
        purchases_to_process = get_unprocessed_purchases_for_seller(
            state.all_purchases, state.processed_purchases, seller
        )
        for p in purchases_to_process:
            logger.info("Processing purchase: %s", p)
            logger.info("Getting detail for %s/%s", p.ejercicio, p.ordencompra)
            try:
                purchase_detail = get_purchase_detail(purchase_detail_url(p))
            except Exception as e:
                logger.warn("Error when getting detail of %s. Exception: %s", p, e)
                state.processed_purchases.append(
                    ProcessedPurchase(
                        **p.to_dict(),
                        processed_at=datetime.now(),
                        status="error",
                        tweet_id=None,
                    )
                )
                continue

            if not any(
                map(
                    lambda line: KEYWORD_TO_CHECK in line["detalle"].lower(),
                    purchase_detail,
                )
            ):
                logger.info("Dropping %s - keyword not found")
                state.processed_purchases.append(
                    ProcessedPurchase(
                        **p.to_dict(),
                        processed_at=datetime.now(),
                        status="dropped",
                        tweet_id=None,
                    )
                )
                continue
            logger.info("Will tweet: %s", p)
            tweet_queue.append(p)

    for i, p in enumerate(
        sorted(
            tweet_queue,
            key=lambda p: datetime.strptime(p.fecha, "%d-%m-%Y")
        )
    ):
        tweet_id: str = ""
        status: str = ""
        logger.info("Tweeting: %s", p)
        try:
            status = tweet_new_purchase(p, twitter_client)
            tweet_id = status.id
            status = "processed"
        except Exception as e:
            logger.error("Could not tweet: %s", e)
            tweet_id = ""
            status = "error"

        state.processed_purchases.append(
            ProcessedPurchase(
                **p.to_dict(),
                processed_at=datetime.now(),
                status=status,
                tweet_id=tweet_id
            )
        )

    _save_state(state)


if __name__ == "__main__":
    dotenv.load_dotenv()
    main()

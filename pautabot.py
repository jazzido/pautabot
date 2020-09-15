import dataclasses
from datetime import datetime
import logging
import os
import pickle
from typing import Any, Dict, List, Optional, Set, Tuple
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
    "https://www.bahia.gob.ar/compras/data/oc/{year}/{ordencompra}"
)

TWEET_TEMPLATE = """
🤖 pautabot reportando nuevo 💸 gasto en pauta publicitaria:

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


def purchase_detail_page_url(purchase: Purchase) -> str:
    return DETAIL_PURCHASE_URL_TEMPLATE.format(
        year=purchase.ejercicio, ordencompra=purchase.ordencompra
    )


def get_advertisement_totals_by_seller() -> Dict[str, float]:
    resp = requests.get(AD_PURCHASES_URL)
    return {row["proveedor"]: float(row["monto"]) for row in resp.json()}


def get_all_purchases() -> List[Purchase]:
    resp = requests.get(ALL_PURCHASES_URL)
    return Purchase.schema().load(resp.json(), many=True)


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


def get_purchase_detail_html(url: str) -> str:
    resp = requests.get(url)
    return resp.text


def tweet_new_purchase(purchase: Purchase, twitter_client: tweepy.API) -> tweepy.Status:
    tweet_body = TWEET_TEMPLATE.format(
        fecha=purchase.fecha,
        proveedor=boldify(purchase.proveedor),
        dependencia=boldify(purchase.dependencia),
        importe=monodigits(str(purchase.importe)),
        url=purchase_detail_page_url(purchase),
    )

    status = twitter_client.update_status(
        tweet_body
    )

    return status


def main():
    logger.info(f"Running {__name__}")
    with open(STATE_FILE, "rb") as sf:
        state: RunState = pickle.load(sf)

    logger.info(
        "Read state. last_run: %s - len(totals_by_seller): %d - len(all_purchases): %d - len(processed_purchases): %d",
        state.last_run,
        len(state.totals_by_seller),
        len(state.all_purchases),
        len(state.processed_purchases),
    )

    logger.info("Getting all purchases")
    all_purchases = get_all_purchases()
    logger.info("Getting ad purchases")
    ad_purchases_totals = get_advertisement_totals_by_seller()

    # Get sellers to find new purchases
    sellers_to_process = diff_totals(state.totals_by_seller, ad_purchases_totals)
    if len(sellers_to_process) == 0:
        logger.info("No changes since %s - Bye.", state.last_run)
    else:
        twitter_client = init_twitter_client()

    for seller in sellers_to_process:
        purchases_to_process = get_unprocessed_purchases_for_seller(
            all_purchases, state.processed_purchases, seller
        )
        for p in purchases_to_process:
            logger.info("Processing purchase: %s", p)
            logger.info("Getting detail page for %s/%s", p.ejercicio, p.ordencompra)
            detail_page_html = get_purchase_detail_html(purchase_detail_page_url(p))

            if KEYWORD_TO_CHECK not in detail_page_html.lower():
                logger.info("Dropping %s - keyword not found")
                state.processed_purchases.append(
                    ProcessedPurchase(
                        **p.to_dict(), processed_at=datetime.now(), status="dropped", tweet_id=None
                    )
                )
                continue

            logger.info("Tweeting: %s", p)
            status = tweet_new_purchase(p, twitter_client)
            state.processed_purchases.append(
                ProcessedPurchase(
                    **p.to_dict(), processed_at=datetime.now(), status="processed", tweet_id=status.id_str
                )
            )

    logger.info("Saving new state")
    with open(STATE_FILE, "wb") as sf:
        pickle.dump(state, sf)


if __name__ == "__main__":
    dotenv.load_dotenv()
    main()

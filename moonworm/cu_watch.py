import json
import logging
import pprint as pp
import time
from os import stat
from re import S
from typing import Any, Dict, List, Optional, cast

import web3
from eth_typing.evm import ChecksumAddress
from moonstreamdb.db import yield_db_session_ctx
from moonstreamdb.models import EthereumLabel, PolygonLabel
from sqlalchemy.orm import Query, Session
from tqdm import tqdm
from web3 import Web3

from moonworm.crawler.moonstream_ethereum_state_provider import (
    MoonstreamEthereumStateProvider,
)
from moonworm.crawler.networks import Network

from .contracts import CU, ERC721
from .crawler.function_call_crawler import (
    ContractFunctionCall,
    FunctionCallCrawler,
    FunctionCallCrawlerState,
    Web3StateProvider,
    utfy_dict,
)
from .crawler.log_scanner import _fetch_events_chunk

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _get_last_crawled_block(
    session: Session, contract_address: ChecksumAddress
) -> Optional[int]:
    """
    Gets the last block that was crawled.
    """

    query = (
        session.query(PolygonLabel)
        .filter(
            PolygonLabel.label == "moonworm",
            PolygonLabel.address == contract_address,
        )
        .order_by(PolygonLabel.block_number.desc())
    )
    if query.count():
        return query.first().block_number
    return None


def _add_function_call_labels(
    session: Session,
    function_calls: List[ContractFunctionCall],
    address: ChecksumAddress,
) -> None:
    """
    Adds a label to a function call.
    """

    existing_function_call_labels = (
        session.query(PolygonLabel)
        .filter(
            PolygonLabel.label == "moonworm",
            PolygonLabel.log_index == None,
            PolygonLabel.address == address,
            PolygonLabel.transaction_hash.in_(
                [call.transaction_hash for call in function_calls]
            ),
        )
        .all()
    )
    # deletin existing labels
    for label in existing_function_call_labels:
        session.delete(label)

    try:
        if existing_function_call_labels:
            logger.info(
                f"Deleting {len(existing_function_call_labels)} existing tx labels:\n{existing_function_call_labels}"
            )
            session.commit()
    except Exception as e:
        try:
            session.commit()
        except:
            logger.error(f"Failed!!!\n{e}")
            session.rollback()

    for function_call in function_calls:
        label = PolygonLabel(
            label="moonworm",
            label_data={
                "type": "tx_call",
                "name": function_call.function_name,
                "caller": function_call.caller_address,
                "args": function_call.function_args,
                "status": function_call.status,
                "gasUsed": function_call.gas_used,
            },
            address=function_call.contract_address,
            block_number=function_call.block_number,
            transaction_hash=function_call.transaction_hash,
            block_timestamp=function_call.block_timestamp,
        )
        session.add(label)
    try:
        session.commit()
    except Exception as e:
        try:
            session.commit()
        except:
            logger.error(f"Failed!!!\n{e}")
            session.rollback()


def _add_event_labels(
    session: Session, events: List[Dict[str, Any]], address: ChecksumAddress
) -> None:
    """
    Adds events to database.
    """

    transactions = [event["transactionHash"] for event in events]
    for ev in events:
        print(ev)
    existing_event_labels = (
        session.query(PolygonLabel)
        .filter(
            PolygonLabel.label == "moonworm",
            PolygonLabel.address == address,
            PolygonLabel.transaction_hash.in_(transactions),
            PolygonLabel.log_index != None,
        )
        .all()
    )

    # deletin existing labels
    for label in existing_event_labels:
        session.delete(label)

    try:
        if existing_event_labels:
            logger.error(
                f"Deleting {len(existing_event_labels)} existing event labels:\n{existing_event_labels}"
            )
            session.commit()
    except Exception as e:
        try:
            session.commit()
        except:
            logger.error(f"Failed!!!\n{e}")
            session.rollback()

    for event in events:
        label = PolygonLabel(
            label="moonworm",
            label_data={
                "type": "event",
                "name": event["event"],
                "args": event["args"],
            },
            address=event["address"],
            block_number=event["blockNumber"],
            transaction_hash=event["transactionHash"],
            block_timestamp=event["blockTimestamp"],
            log_index=event["logIndex"],
        )
        session.add(label)
    try:
        session.commit()
    except Exception as e:
        try:
            session.commit()
        except:
            logger.error(f"Failed!!!\n{e}")
            session.rollback()


class MockState(FunctionCallCrawlerState):
    def __init__(self) -> None:
        self.state: List[ContractFunctionCall] = []

    def get_last_crawled_block(self) -> int:
        """
        Returns the last block number that was crawled.
        """
        return 0

    def register_call(self, function_call: ContractFunctionCall) -> None:
        """
        Processes the given function call (store it, etc.).
        """
        self.state.append(function_call)

    def flush(self) -> None:
        """
        Flushes cached state to storage layer.
        """
        self.state = []


def watch_cu_contract(
    web3: Web3,
    contract_address: ChecksumAddress,
    contract_abi: List[Dict[str, Any]],
    num_confirmations: int = 10,
    sleep_time: float = 1,
    start_block: Optional[int] = None,
    force_start: bool = False,
    use_moonstream_web3_provider: bool = False,
) -> None:
    """
    Watches a contract for events and calls.
    """
    if force_start and start_block is None:
        raise ValueError("start_block must be specified if force_start is True")

    with yield_db_session_ctx() as session:
        function_call_state = MockState()
        web3_state = Web3StateProvider(web3)
        eth_state_provider = web3_state
        if use_moonstream_web3_provider:
            eth_state_provider = MoonstreamEthereumStateProvider(
                web3, network=Network.polygon, session=session
            )

        crawler = FunctionCallCrawler(
            function_call_state,
            eth_state_provider,
            contract_abi,
            [web3.toChecksumAddress(contract_address)],
        )

        last_crawled_block = _get_last_crawled_block(session, contract_address)
        if start_block is None:
            if last_crawled_block is not None:
                current_block = last_crawled_block
                logger.info(f"Starting from block {current_block}, last crawled block")
            else:
                current_block = web3.eth.blockNumber - num_confirmations * 2
                logger.info(f"Starting from block {current_block}, current block")
        else:
            current_block = start_block
            if not force_start and last_crawled_block is not None:
                if start_block > last_crawled_block:
                    logger.info(
                        f"Starting from block {start_block}, last crawled block {last_crawled_block}"
                    )
                else:
                    current_block = last_crawled_block
                    logger.info(f"Starting from last crawled block {current_block}")

        event_abis = [item for item in contract_abi if item["type"] == "event"]

        while True:
            session.query(PolygonLabel).limit(1).one()
            time.sleep(sleep_time)
            end_block = min(web3.eth.blockNumber - num_confirmations, current_block + 5)
            if end_block < current_block:
                sleep_time *= 2
                continue

            sleep_time /= 2

            logger.info("Getting txs")
            crawler.crawl(current_block, end_block)
            if function_call_state.state:
                _add_function_call_labels(
                    session, function_call_state.state, contract_address
                )
                logger.info(f"Got  {len(function_call_state.state)} transaction calls:")
                function_call_state.flush()

            logger.info("Getting events")
            all_events = []
            for event_abi in event_abis:
                raw_events = _fetch_events_chunk(
                    web3,
                    event_abi,
                    current_block,
                    end_block,
                    [contract_address],
                )

                for raw_event in raw_events:

                    event = {
                        "event": raw_event["event"],
                        "args": json.loads(
                            Web3.toJSON(utfy_dict(dict(raw_event["args"])))
                        ),
                        "address": raw_event["address"],
                        "blockNumber": raw_event["blockNumber"],
                        "transactionHash": raw_event["transactionHash"].hex(),
                        "blockTimestamp": crawler.ethereum_state_provider.get_block_timestamp(
                            raw_event["blockNumber"]
                        ),
                        "logIndex": raw_event["logIndex"],
                    }
                    all_events.append(event)

            if all_events:
                print(f"Got {len(all_events)} events:")
                _add_event_labels(session, all_events, contract_address)
            logger.info(f"Current block {end_block + 1}")
            current_block = end_block + 1

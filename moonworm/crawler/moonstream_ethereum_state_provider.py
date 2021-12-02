import logging
from typing import Any, Dict, List, Optional, Union
from eth_typing.evm import ChecksumAddress
from hexbytes.main import HexBytes
from moonstreamdb.db import yield_db_session_ctx
from moonstreamdb.models import (
    EthereumLabel,
    EthereumTransaction,
    PolygonLabel,
    PolygonTransaction,
)
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import NO_ARG
from web3 import Web3

from .networks import Network, MODELS
from .ethereum_state_provider import EthereumStateProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# TODO(yhtiyar) When getting block from db, filter it by `to` address, it will be faster
# also get blocks in bunch
class MoonstreamEthereumStateProvider(EthereumStateProvider):
    """
    Implementation of EthereumStateProvider with moonstream.
    """

    def __init__(
        self, w3: Web3, network: Network, db_session: Optional[Session] = None
    ):
        self.w3 = w3
        self.db_session = db_session

        self.blocks_model = MODELS[network]["blocks"]
        self.transactions_model = MODELS[network]["transactions"]
        self.labels_model = MODELS[network]["labels"]
        self.network = network
        self.blocks_cache = {}

    def set_db_session(self, db_session: Session):
        self.db_session = db_session

    def clear_db_session(self):
        self.db_session = None

    def get_transaction_reciept(self, transaction_hash: str) -> Dict[str, Any]:
        return self.w3.eth.get_transaction_receipt(transaction_hash)

    def get_last_block_number(self) -> int:
        last_block = (
            self.db_session.query(self.blocks_model)
            .order_by(self.blocks_model.block_number.desc())
            .limit(1)
            .one_or_none()
        )
        if last_block is None:
            raise Exception(
                f"No blocks in database, for network: {self.network.value} "
            )
        return last_block.block_number

    @staticmethod
    def _transform_to_w3_tx(
        tx_raw: Union[EthereumTransaction, PolygonTransaction],
    ) -> Dict[str, Any]:
        tx = {
            "blockNumber": tx_raw.block_number,
            "from": tx_raw.from_address,
            "gas": tx_raw.gas,
            "gasPrice": tx_raw.gas_price,
            "hash": HexBytes(tx_raw.hash),
            "input": tx_raw.input,
            "maxFeePerGas": tx_raw.max_fee_per_gas,
            "maxPriorityFeePerGas": tx_raw.max_priority_fee_per_gas,
            "nonce": tx_raw.nonce,
            "to": tx_raw.to_address,
            "transactionIndex": tx_raw.transaction_index,
            "value": tx_raw.value,
        }
        return tx

    def _get_block_from_db(
        self, block_number: int, batch_load_count: int = 100
    ) -> Optional[Dict[str, Any]]:
        if self.db_session is None:
            return None

        raw_blocks = (
            self.db_session.query(self.blocks_model)
            .filter(self.blocks_model.block_number >= block_number)
            .order_by(self.blocks_model.block_number.asc())
            .limit(batch_load_count)
        )
        blocks = {raw_block.block_number: raw_block for raw_block in raw_blocks}

        if blocks.get(block_number) is None:
            return None
        # Assuming that all tx's from a block are written to db in the same db transaction
        raw_block_transactions = (
            self.db_session.query(self.transactions_model)
            .filter(
                self.transactions_model.block_number.in_(
                    [block_number for block_number in blocks]
                )
            )
            .order_by(self.transactions_model.transaction_index.asc())
            .all()
        )

        block_transactions = {}

        for raw_tx in raw_block_transactions:
            if block_transactions.get(raw_tx.block_number) is None:
                block_transactions[raw_tx.block_number] = []
            block_transactions[raw_tx.block_number].append(raw_tx)

        if block_transactions.get(block_number) is None:
            return None

        if len(self.blocks_cache) > 500:
            self.blocks_cache = {}

        for block, txs in block_transactions.items():
            self.blocks_cache[block] = {
                "timestamp": blocks[block].timestamp,
                "transactions": [self._transform_to_w3_tx(tx) for tx in txs],
            }

        return self.blocks_cache[block_number]

    def _get_block(self, block_number: int) -> Dict[str, Any]:
        log_prefix = f"MoonstreamEthereumStateProvider._get_block: block_number={block_number},network={self.network.value}"
        logger.debug(log_prefix)
        if block_number in self.blocks_cache:
            logger.debug(f"{log_prefix} - found in cache")
            return self.blocks_cache[block_number]

        block = self._get_block_from_db(block_number)
        if block is None:
            logger.debug(f"{log_prefix} - not found in db or cache, fetching from web3")
            block = self.w3.eth.getBlock(block_number, full_transactions=True)
        else:
            logger.debug(f"{log_prefix} - found in db")

        # clear cache if it grows too large
        if len(self.blocks_cache) > 500:
            self.blocks_cache = {}

        self.blocks_cache[block_number] = block
        return block

    def get_block_timestamp(self, block_number: int) -> int:
        logger.debug(
            f"MoonstreamEthereumStateProvider.get_block_timestamp: block_number={block_number},network={self.network.value}"
        )
        block = self._get_block(block_number)
        return block["timestamp"]

    def get_transactions_to_address(
        self, address: ChecksumAddress, block_number: int
    ) -> List[Dict[str, Any]]:
        logger.debug(
            f"MoonstreamEthereumStateProvider.get_transactions_to_address: address={address},block_number={block_number},network={self.network.value}"
        )
        block = self._get_block(block_number)

        all_transactions = block["transactions"]
        return [tx for tx in all_transactions if tx["to"] == address]

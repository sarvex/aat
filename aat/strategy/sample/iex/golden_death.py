import os
import math
import pandas as pd  # type: ignore
from typing import Any, Optional, List
from aat import (
    Strategy,
    Event,
    Order,
    Trade,
    Side,
    Instrument,
    InstrumentType,
    ExchangeType,
)


class GoldenDeathStrategy(Strategy):
    def __init__(
        self,
        symbol: str,
        long_ma: int = 30,
        short_ma: int = 10,
        bail_hour: int = 15,
        bail_minute: int = 45,
        *args: Any,
        **kwargs: Any
    ) -> None:
        super(GoldenDeathStrategy, self).__init__(*args, **kwargs)

        # Long moving average size
        self._long_ma = long_ma

        # Short moving average size
        self._short_ma = short_ma

        # Symbol to trade
        self._symbol = symbol

        # Moving average lists
        self._long_ma_list: List[float] = []
        self._short_ma_list: List[float] = []

        # State vars
        self._triggered = False
        self._entered = False

        # Orders
        self._buy_order: Optional[Order] = None
        self._volume = 0
        self._sell_order: Optional[Order] = None

        # bail time
        self._bail_hour = bail_hour
        self._bail_minute = bail_minute

    async def onStart(self, event: Event) -> None:
        # Get available instruments from exchange
        await self.subscribe(
            Instrument(
                name=self._symbol,
                type=InstrumentType.EQUITY,
                exchange=ExchangeType("iex"),
            )
        )

    async def onTrade(self, event: Event) -> None:
        """Called whenever a `Trade` event is received"""
        trade: Trade = event.target  # type: ignore

        # append prices
        self._long_ma_list.append(trade.price)
        self._short_ma_list.append(trade.price)

        # adding to list
        self._long_ma_list = self._long_ma_list[-self._long_ma :]
        self._short_ma_list = self._short_ma_list[-self._short_ma :]

        if len(self._long_ma_list) < self._long_ma:
            return

        # dont trade in first 15 minutes
        if self.now().hour == 9 and self.now().minute <= 45:
            return

        long_mvg_av = (
            pd.Series(self._long_ma_list)
            .rolling(self._long_ma, min_periods=self._long_ma)
            .mean()
            .iloc[-1]
        )
        short_mvg_av = (
            pd.Series(self._short_ma_list)
            .rolling(self._short_ma, min_periods=self._short_ma)
            .mean()
            .iloc[-1]
        )
        long_mvg_av = long_mvg_av + (long_mvg_av * 0.005)
        # States
        #
        # Not Entered, Not Triggered -> if long_ma > short_ma -> Not Entered, Triggered (Wait for short av to move above)
        # Not Entered, Not Triggered -> if long_ma <= short_ma -> Not Entered, Not Triggered (Not ready yet)
        # Not Entered, Triggered -> if long_ma > short_ma -> Not Entered, Triggered (Wait for short to move above)
        # Not Entered, Triggered -> if long_ma <= short_ma -> Entered, Triggered (BUY)
        # Entered, Triggered -> if long_ma > short_ma -> Not Entered, Triggered (SELL)
        # Entered, Triggered -> if long_ma <= short_ma -> Entered, Triggered (Wait for short to move below)
        if self._entered:
            if not self._triggered:
                raise Exception("Never in this state")
            if long_mvg_av > short_mvg_av:
                    # Entered, Triggered -> if long_ma > short_ma -> Not Entered, Triggered (SELL)
                if not self._sell_order:
                    self._sell_order = Order(
                        side=Side.SELL,
                        price=trade.price,
                        volume=self._volume,
                        instrument=trade.instrument,
                        order_type=Order.Types.MARKET,
                        exchange=trade.exchange,
                    )
                    print(f"submitting sell order: {self._sell_order}")
                    await self.newOrder(self._sell_order)
            elif (
                        not self._sell_order
                        and self.now().hour == self._bail_hour
                        and self.now().minute >= self._bail_minute
                    ):
                self._sell_order = Order(
                    side=Side.SELL,
                    price=trade.price,
                    volume=self._volume,
                    instrument=trade.instrument,
                    order_type=Order.Types.MARKET,
                    exchange=trade.exchange,
                )
                print(f"submitting sell order: {self._sell_order}")
                await self.newOrder(self._sell_order)

        elif not self._triggered:
            self._triggered = long_mvg_av > short_mvg_av
        elif long_mvg_av <= short_mvg_av:
                    # Not Entered, Triggered -> if long_ma <= short_ma -> Entered, Triggered (BUY)
            if not self.orders(trade.instrument):
                self._volume = math.ceil(1000 / trade.price)
                self._buy_order = Order(
                    side=Side.BUY,
                    price=trade.price,
                    volume=self._volume,
                    instrument=trade.instrument,
                    order_type=Order.Types.MARKET,
                    exchange=trade.exchange,
                )
                print(f"submitting buy order: {self._buy_order}")
                await self.newOrder(self._buy_order)

    async def onTraded(self, event: Event) -> None:
        trade: Trade = event.target  # type: ignore
        if self._buy_order and self._buy_order == trade.my_order:
            self._entered = True
            self._buy_order = None
        elif self._sell_order and self._sell_order == trade.my_order:
            self._entered = False
            self._sell_order = None

    async def onRejected(self, event: Event) -> None:
        print("order rejected")
        import sys

        sys.exit(0)

    async def onExit(self, event: Event) -> None:
        print("Finishing...")

        if not os.environ.get("TESTING"):
            self.performanceCharts()


if __name__ == "__main__":
    from aat import TradingEngine, parseConfig

    cfg = parseConfig(
        [
            "--trading_type",
            "backtest",
            "--exchanges",
            "aat.exchange.public.iex:IEX,pk_75e8105f05d342a8abb1630c8894376c,True,1m,,,,",
            "--strategies",
            "aat.strategy.sample.iex.golden_death:GoldenDeathStrategy,SPY",
        ]
    )
    """
    [general]
    verbose=0
    trading_type=backtest

    [exchange]
    exchanges=
        aat.exchange.public.iex:IEX,pk_75e8105f05d342a8abb1630c8894376c,True,1m,,,,

    [strategy]
    strategies =
        aat.strategy.sample.iex.momentum:MomentumStrategy,SPY-EQUITY,25,45,-10,10000

    """
    print(cfg)
    t = TradingEngine(**cfg)
    t.start()

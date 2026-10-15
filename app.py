from __future__ import annotations
import time
import pandas as pd
import streamlit as st
import plotly.express as px
from core import DEFAULTS, indicators, backtest
from data_sources import UNIVERSE, fetch_history, fetch_universe
from paper_broker import PaperBroker

st.set_page_config(page_title="Trade Agent 500", page_icon="📈", layout="wide")
st.title("📈 Trade Agent 500")
st.caption("Swing trading multi-activo · simulación exclusivamente · sin órdenes reales")
with st.sidebar:
    st.header("Configuración")
    initial_cash=st.number_input("Capital virtual inicial (€)", min_value=50.0, max_value=100000.0, value=500.0, step=50.0)
    risk_pct=st.slider("Riesgo por operación (%)", 0.25, 2.0, 1.0, 0.25)/100
    max_positions=st.slider("Máximo de posiciones",1,8,4)
    min_score=st.slider("Puntuación mínima",50,95,70,5)
    period=st.selectbox("Histórico",["1y","2y","5y"],index=1)
    markets=st.multiselect("Mercados",list(UNIVERSE.keys()),default=list(UNIVERSE.keys()))
    st.warning("Yahoo Finance es una fuente gratuita no oficial; puede tener límites, retrasos o cambios de cobertura. No usar para ejecución real.")

cfg={**DEFAULTS,"initial_cash_eur":initial_cash,"risk_per_trade":risk_pct,"max_open_positions":max_positions,"minimum_score":min_score}
broker=PaperBroker(initial_cash=initial_cash,commission=cfg["commission_rate"],slippage=cfg["slippage_rate"])
tabs=st.tabs(["Resumen","Escáner","Backtesting","Cartera virtual","Guía"])

with tabs[0]:
    state=broker.state()
    positions=state["positions"]
    st.subheader("Cuenta simulada")
    c1,c2,c3,c4=st.columns(4)
    c1.metric("Efectivo",f"{state['cash']:.2f} €")
    c2.metric("Capital inicial",f"{state['initial_cash']:.2f} €")
    c3.metric("Posiciones",len(positions),f"máx. {max_positions}")
    c4.metric("Comisión por lado",f"{cfg['commission_rate']*100:.2f}%")
    st.info("El patrimonio total se calcula como efectivo + valor de mercado de las posiciones; las cotizaciones se actualizan al pulsar el escáner.")
    st.markdown("**Flujo:** datos gratuitos → filtros → señales → control de riesgo → órdenes virtuales → registro SQLite.")
    if st.button("Restablecer cuenta virtual",type="secondary"):
        broker.reset(initial_cash); st.success("Cuenta virtual restablecida."); st.rerun()

with tabs[1]:
    st.subheader("Escáner de oportunidades")
    st.write("Descarga datos diarios y puntúa activos. La primera ejecución puede tardar según la disponibilidad del proveedor.")
    if st.button("Analizar mercados ahora",type="primary"):
        if not markets:
            st.error("Selecciona al menos un mercado.")
        else:
            with st.spinner("Descargando datos públicos y calculando señales…"):
                all_data=fetch_universe(markets,period=period)
                rows=[]
                for ticker,df in all_data.items():
                    calc=indicators(df,cfg)
                    if calc.empty: continue
                    last=calc.iloc[-1]
                    rows.append({"Activo":ticker,"Cierre":float(last.Close),"RSI":float(last.rsi) if pd.notna(last.rsi) else None,
                                 "Puntuación":round(float(last.score),1),"Señal":bool(last.signal),
                                 "ATR":float(last.atr) if pd.notna(last.atr) else None,
                                 "Fecha":str(calc.index[-1].date()),"Volumen x":round(float(last.volume_ratio),2) if pd.notna(last.volume_ratio) else None,
                                 "Datos":len(df)})
                if rows:
                    result=pd.DataFrame(rows).sort_values(["Señal","Puntuación"],ascending=False)
                    st.session_state["scan_result"]=result
                    st.session_state["scan_markets"]=all_data
                else: st.error("No se pudieron obtener datos suficientes. Comprueba conexión o intenta más tarde.")
    if "scan_result" in st.session_state:
        result=st.session_state["scan_result"]
        st.dataframe(result,use_container_width=True,hide_index=True)
        candidates=result[(result.Señal==True)&(result.Puntuación>=min_score)].sort_values("Puntuación",ascending=False)
        st.markdown(f"**Candidatos válidos:** {len(candidates)}")
        if st.button("Ejecutar ciclo de trading virtual"):
            state=broker.state(); messages=[]
            # Primero revisar stops/objetivos y salida por tendencia.
            for p in list(state["positions"]):
                ticker,units,entry,stop,target,entry_fee,opened=p
                try:
                    df=fetch_history(ticker,period="6mo")
                    calc=indicators(df,cfg)
                    last=calc.iloc[-1]
                    if last.Low<=stop: ok,msg=broker.sell(ticker,min(float(last.Open),stop) if last.Open<stop else stop,"stop")
                    elif last.High>=target: ok,msg=broker.sell(ticker,target,"target")
                    elif last.Close<last.ema_slow: ok,msg=broker.sell(ticker,float(last.Close),"trend_exit")
                    else: continue
                    messages.append(msg)
                except Exception as e: messages.append(f"{ticker}: no se pudo evaluar salida ({e})")
            state=broker.state()
            for _,r in candidates.iterrows():
                if len(broker.state()["positions"])>=max_positions: break
                if r.Activo in [p[0] for p in broker.state()["positions"]]: continue
                df=st.session_state["scan_markets"].get(r.Activo)
                if df is None or len(df)<60: continue
                calc=indicators(df,cfg); last=calc.iloc[-1]
                ok,msg=broker.buy(r.Activo,float(last.Close),float(last.atr),state["cash"],risk_fraction=risk_pct,max_positions=max_positions)
                if ok: messages.append(msg); state=broker.state()
            if not messages: st.info("No se han ejecutado operaciones: no hay señal válida o los límites de riesgo impiden entrar.")
            for m in messages: st.write("• "+m)
            st.warning("Las órdenes del ciclo son virtuales. Las entradas se simulan al último cierre disponible y no representan una ejecución real al siguiente open.")

with tabs[2]:
    st.subheader("Backtesting de una estrategia")
    options=[x for m in markets for x in UNIVERSE.get(m,[])]
    if not options: options=UNIVERSE["ETF"]
    ticker=st.selectbox("Activo a probar",options,index=0)
    test_period=st.selectbox("Periodo de prueba",["1y","2y","5y"],index=1,key="bt_period")
    if st.button("Ejecutar backtest",type="primary"):
        with st.spinner(f"Descargando histórico de {ticker}…"):
            df=fetch_history(ticker,period=test_period)
            if df.empty: st.error("No hay datos para este activo.")
            else:
                res=backtest(df,cfg); metrics=res["metrics"]
                if "error" in metrics: st.error(metrics["error"])
                else:
                    a,b,c,d=st.columns(4)
                    a.metric("Rentabilidad neta",f"{metrics['net_return_pct']:.2f}%")
                    b.metric("Patrimonio final",f"{metrics['final_equity']:.2f} €")
                    c.metric("Drawdown máximo",f"{metrics['max_drawdown_pct']:.2f}%")
                    d.metric("Operaciones",metrics["trades"])
                    st.caption(f"Win rate: {metrics['win_rate_pct']:.1f}% · Profit factor: {metrics['profit_factor']:.2f} · Sharpe anualizado: {metrics['sharpe_annualized']:.2f}")
                    eq=res["equity"].reset_index()
                    st.plotly_chart(px.line(eq,x="date",y="equity",title="Patrimonio simulado (€)"),use_container_width=True)
                    if not res["trades"].empty: st.dataframe(res["trades"],use_container_width=True,hide_index=True)
                    st.download_button("Descargar operaciones CSV",res["trades"].to_csv(index=False),file_name=f"trades_{ticker}.csv",mime="text/csv")
                    st.warning("Un backtest aislado no prueba que exista ventaja estadística. Repite en varios activos y periodos fuera de muestra; el resultado no es una predicción.")

with tabs[3]:
    st.subheader("Cartera y registro virtual")
    state=broker.state()
    if state["positions"]:
        pos_df=pd.DataFrame(state["positions"],columns=["Activo","Unidades","Entrada","Stop","Objetivo","Comisión entrada","Apertura"])
        st.dataframe(pos_df,use_container_width=True,hide_index=True)
        ticker_close=st.selectbox("Cerrar posición virtual",[p[0] for p in state["positions"]])
        if st.button("Cerrar al último cierre disponible"):
            df=fetch_history(ticker_close,period="6mo")
            if not df.empty:
                ok,msg=broker.sell(ticker_close,float(df.Close.iloc[-1]),"manual_virtual")
                st.success(msg); st.rerun()
    else: st.info("No hay posiciones virtuales abiertas.")
    if state["trades"]:
        trades=pd.DataFrame(state["trades"],columns=["Fecha","Activo","Lado","Unidades","Precio","Comisión","P/L neto","Motivo"])
        st.dataframe(trades,use_container_width=True,hide_index=True)
        st.download_button("Descargar registro CSV",trades.to_csv(index=False),file_name="paper_trades.csv",mime="text/csv")
    else: st.write("Todavía no hay operaciones registradas.")

with tabs[4]:
    st.subheader("Reglas y limitaciones")
    st.markdown("""
- **Capital virtual:** 500 € por defecto; estado guardado en SQLite local.
- **Riesgo por operación:** 1 % del patrimonio; tamaño de posición limitado además al 30 % del patrimonio.
- **Estrategia:** EMA20 > EMA50, cierre > EMA50, ruptura del máximo previo de 20 sesiones, RSI 50–70 y ATR válido.
- **Salida:** stop de 2 ATR, objetivo teórico de 3R y salida por deterioro de tendencia.
- **Costes:** comisión del 0,10 % por lado y deslizamiento del 0,10 % por lado como supuestos configurables, no tarifas garantizadas.
- **Mercados:** el escáner usa símbolos de Yahoo Finance para cripto, acciones y ETF. La cobertura y el retraso pueden variar.
- **Simulación:** no se envían órdenes reales. El ciclo inicial usa cotizaciones descargadas; no equivale a ejecución histórica exacta al siguiente precio de apertura.
- **Riesgo de modelo:** el backtest de un activo no simula una cartera multi-activo completa ni garantiza resultados futuros.
    """)
    st.code("streamlit run app.py",language="bash")

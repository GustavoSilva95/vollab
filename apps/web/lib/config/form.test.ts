import { describe, expect, it } from 'vitest';
import type { ConfigParamsOutput } from '@vollab/api-types';
import { configFormSchema, diffParams, toConfigParams, toFormValues } from './form';

const params: ConfigParamsOutput = {
  collection: { liquidity: { min_trades: 20 } } as ConfigParamsOutput['collection'],
  vol: { constant_maturity_bd: 21, ci_level: 0.9 } as ConfigParamsOutput['vol'],
  forecast: { ewma_lambda: 0.94, selected_model: 'ewma' } as ConfigParamsOutput['forecast'],
  costs: {
    option_fee_rate: 0.00134,
    underlying_fee_rate: 0.0003,
    brokerage_per_order_brl: 0,
    brokerage_rate: 0,
    reference_contracts: 100,
    tick_brl: 0.01,
    spread_floors_brl: {},
    spread_min_trades: 20,
    spread_lookback_bd: 5,
    moneyness_bands: [0.95, 1.05],
    hedge_interval_bd: 1,
  },
  edge: {
    normal_spread_default: 0.15,
    normal_spread_lookback_bd: 252,
    threshold_vol_pts: 0.01,
    iv_rank_min_days: 60,
    skew_moneyness: [0.95, 1.05],
  },
  sizing: { capital_brl: null, kelly_fraction: 0.25 } as ConfigParamsOutput['sizing'],
  risk: {
    stress_gap: 0.1,
    stress_vol_pts: 0.1,
    crisis_horizon_bd: 5,
    crisis_episodes: [],
    crisis_overrides: { PETR4: { mar2020: { price_shock: -0.3, vol_shock: 0.5 } } },
    limits: {
      max_stress_loss_fraction: 0.2,
      max_abs_vega_fraction: 0.01,
      max_underlying_share: 0.5,
      max_expiry_share: 0.6,
    },
  } as ConfigParamsOutput['risk'],
  journal: { residual_max_ratio: 0.15, residual_min_brl: 50 },
  simulation: { delta_band: 0.1 } as ConfigParamsOutput['simulation'],
  management: {
    hedge_interval_bd: null,
    exit_dte_bd: 5,
    profit_target_fraction: null,
    stop_loss_fraction: null,
    roll_min_dte_bd: 10,
    dividend_lead_bd: 5,
  },
};

describe('formulário da configuração (PRD 1.8 §8.1)', () => {
  it('Etapa 7: limites aninhados, stress, diário e capital (vazio = não informado)', () => {
    const v = toFormValues(params);
    expect(v.max_stress_loss_fraction).toBe('20');
    expect(v.max_abs_vega_fraction).toBe('1');
    expect(v.stress_vol_pts).toBe('10');
    expect(v.residual_min_brl).toBe('50');
    expect(v.capital).toBe('');
    const out = toConfigParams({ ...v, max_expiry_share: '70', capital: '150000,50', note: 'x' }, params);
    expect(out.risk?.limits?.max_expiry_share).toBe(0.7);
    expect(out.risk?.limits?.max_stress_loss_fraction).toBe(0.2);
    expect(out.risk?.crisis_overrides).toEqual(params.risk?.crisis_overrides); // fora do formulário, intacto
    expect(out.sizing?.capital_brl).toBe(150000.5);
    expect(toConfigParams({ ...v, capital: '', note: 'x' }, params).sizing?.capital_brl).toBeNull();
    const bad = configFormSchema.safeParse({ ...v, capital: 'abc', max_underlying_share: '0', note: 'x' });
    expect(bad.success).toBe(false);
  });

  it('Etapa 8: gestão com regras desligáveis (vazio ↔ null) e meta/stop em %', () => {
    const v = toFormValues(params);
    expect(v.hedge_alert_interval_bd).toBe('');
    expect(v.profit_target_fraction).toBe('');
    expect(v.stop_loss_fraction).toBe('');
    expect(v.exit_dte_bd).toBe('5');
    expect(v.roll_min_dte_bd).toBe('10');
    expect(configFormSchema.safeParse({ ...v, note: 'x' }).success).toBe(true);
    const out = toConfigParams({ ...v, stop_loss_fraction: '100', hedge_alert_interval_bd: '3', exit_dte_bd: '', note: 'x' }, params);
    expect(out.management).toEqual({
      hedge_interval_bd: 3,
      exit_dte_bd: null,
      profit_target_fraction: null,
      stop_loss_fraction: 1,
      roll_min_dte_bd: 10,
      dividend_lead_bd: 5,
    });
    expect(out.costs?.hedge_interval_bd).toBe(1); // o intervalo do custo (Leland) é outro campo
    const bad = configFormSchema.safeParse({ ...v, roll_min_dte_bd: '', stop_loss_fraction: '0', note: 'x' });
    expect(bad.error?.issues.map((i) => i.path[0])).toEqual(expect.arrayContaining(['roll_min_dte_bd', 'stop_loss_fraction']));
  });

  it('mostra % e pontos de vol na unidade da tela, a partir dos decimais da API', () => {
    const v = toFormValues(params);
    expect(v.option_fee_rate).toBe('0,134');
    expect(v.normal_spread_default).toBe('15');
    expect(v.threshold_vol_pts).toBe('1');
    expect(v.ci_level).toBe('90');
    expect(v.band_low).toBe('0,95');
    expect(v.note).toBe('');
  });

  it('volta para decimal e preserva o resto do snapshot', () => {
    const v = { ...toFormValues(params), threshold_vol_pts: '2,5', brokerage_per_order_brl: '4,9', note: 'teste' };
    const out = toConfigParams(v, params);
    expect(out.edge?.threshold_vol_pts).toBe(0.025);
    expect(out.costs?.brokerage_per_order_brl).toBe(4.9);
    expect(out.costs?.option_fee_rate).toBe(0.00134);
    expect(out.forecast?.selected_model).toBe('ewma'); // campo fora do formulário fica igual
    expect(out.costs?.moneyness_bands).toEqual([0.95, 1.05]);
  });

  it('valida faixas e a nota', () => {
    const ok = configFormSchema.safeParse({ ...toFormValues(params), note: 'x' });
    expect(ok.success).toBe(true);
    const bad = configFormSchema.safeParse({
      ...toFormValues(params),
      threshold_vol_pts: '-1',
      reference_contracts: '1,5',
      band_low: '1,1',
      note: '',
    });
    expect(bad.success).toBe(false);
    const paths = bad.error?.issues.map((i) => i.path[0]);
    expect(paths).toEqual(expect.arrayContaining(['threshold_vol_pts', 'reference_contracts', 'band_high', 'note']));
  });

  it('diff entre versões lista só o que mudou', () => {
    const next = structuredClone(params);
    next.edge!.threshold_vol_pts = 0.02;
    expect(diffParams(params, next)).toEqual([{ path: 'edge.threshold_vol_pts', before: '0.01', after: '0.02' }]);
    expect(diffParams(params, params)).toEqual([]);
  });
});

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
};

describe('formulário da configuração (PRD 1.8 §8.1)', () => {
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

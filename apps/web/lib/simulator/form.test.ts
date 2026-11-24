/**
 * Formulários do simulador (PRD 1.9 §5.8): conversão das entradas digitadas para o contrato (sem %
 * e sem float em dinheiro) e a mesma regra de override do engine.
 */
import { describe, expect, it } from 'vitest';
import type { SizingResponse } from '@vollab/api-types';
import fixture from '@/components/cockpit/simulator/__fixtures__/long-straddle-sizing.json';
import { overrideReasons, simulatorSchema, toPositionCreate, toSizingRequest, type SimulatorValues } from './form';

const data = fixture as unknown as SizingResponse;

const base: SimulatorValues = {
  structure: 'long_straddle',
  call: '892',
  put: '977',
  manualSpot: '',
  manualCall: '',
  manualPut: '',
  manualAt: '2026-11-19T17:30',
  capital: '100000',
  marginPerLot: '',
  lots: '3',
};

describe('toSizingRequest', () => {
  it('monta pernas, capital e lotes sem preços manuais', () => {
    expect(toSizingRequest('PETR4', base)).toEqual({
      ticker: 'PETR4',
      structure: 'long_straddle',
      legs: [{ series_id: 892 }, { series_id: 977 }],
      lots: 3,
      capital_brl: '100000',
    });
  });

  it('preços manuais e margem levam a hora no fuso da B3', () => {
    const body = toSizingRequest('PETR4', { ...base, manualSpot: '42,50', manualCall: '1,80', marginPerLot: '250' });
    const at = '2026-11-19T17:30:00-03:00';
    expect(body.legs[0]).toEqual({ series_id: 892, manual_price_brl: '1.80', manual_price_at: at });
    expect(body.legs[1]).toEqual({ series_id: 977 });
    expect(body).toMatchObject({ manual_spot_brl: '42.50', manual_spot_at: at, margin_per_lot_brl: '250', margin_at: at });
  });

  it('venda coberta tem só a call; a validação exige a put nas outras', () => {
    expect(toSizingRequest('PETR4', { ...base, structure: 'covered_call', put: '' }).legs).toEqual([{ series_id: 892 }]);
    expect(simulatorSchema.safeParse({ ...base, put: '' }).success).toBe(false);
    expect(simulatorSchema.safeParse({ ...base, structure: 'covered_call', put: '' }).success).toBe(true);
    expect(simulatorSchema.safeParse({ ...base, capital: '-1' }).success).toBe(false);
    expect(simulatorSchema.safeParse({ ...base, lots: '0' }).success).toBe(false);
  });
});

describe('overrideReasons', () => {
  it('nada a justificar dentro da regra; justifica direção oposta e lotes acima do sugerido', () => {
    expect(overrideReasons(data.simulation, data.sizing, 66)).toEqual([]);
    expect(overrideReasons(data.simulation, data.sizing, 67)).toEqual(['67 lote(s) acima do sugerido (66)']);
    const opposite = { ...data.simulation, direction: 'sell' as const, direction_match: false };
    expect(overrideReasons(opposite, { ...data.sizing, n_final: 0 }, 1)).toEqual([
      'direção da estrutura oposta à do sinal',
      '1 lote(s) acima do sugerido (0)',
    ]);
    expect(overrideReasons({ ...data.simulation, state: 'inconclusive' }, data.sizing, 1)).toEqual([
      'semáforo em inconclusive',
    ]);
  });
});

describe('toPositionCreate', () => {
  it('envia só insumos e o executado, com a versão de configuração da simulação', () => {
    const request = toSizingRequest('PETR4', base);
    const body = toPositionCreate(request, data.simulation, {
      lots: '2',
      prices: ['1,55', ''],
      fees: ['0,20', ''],
      stockPrice: '',
      executedAt: '2026-11-19T17:45',
      note: ' teste ',
      overrideReason: '',
    });
    expect(body).toMatchObject({
      ticker: 'PETR4',
      lots: 2,
      base_config_version_id: data.simulation.config_version_id,
      executed_at: '2026-11-19T17:45:00-03:00',
      note: 'teste',
    });
    expect(body.executed_legs).toEqual([
      { series_id: data.simulation.legs[0]!.series_id, price_brl: '1.55', fees_brl: '0.20' },
      { series_id: data.simulation.legs[1]!.series_id, price_brl: data.simulation.legs[1]!.price_brl, fees_brl: '0' },
    ]);
    expect(body).not.toHaveProperty('override_reason');
    expect(body).not.toHaveProperty('stock');
  });
});

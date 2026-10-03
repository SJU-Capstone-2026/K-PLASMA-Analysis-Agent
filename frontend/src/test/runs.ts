import type { FullRun } from 'agent';
export function syntheticRun(biasPower = 600, pressure = 6, sourcePower = 300): FullRun {
 const runId = `RUN-P${String(pressure).padStart(2,'0')}-S${sourcePower}-B${String(biasPower).padStart(4,'0')}`;
 return {runId, runVersionId:`v-${runId}`,pressure,sourcePower,biasPower,
 metrics:{ionFlux:2,meanIonEnergy:30+pressure,iedWidth:biasPower ? 8 : null},
 units:{pressure:'mTorr',sourcePower:'W',biasPower:'W',ionFlux:'10¹⁸ m⁻²s⁻¹',meanIonEnergy:'eV',iedWidth:'eV'},
 convergenceStatus:'CONVERGED',qualityStatus:'VERIFIED',catalogStatus:'READY',registeredAt:'2026-01-01T00:00:00Z',presentationScore:1,note:'',
 analysis:{hasDistribution:!!biasPower,strictConvergence:false,finalResidualMax:2e-8,electronTemperature:2,ionTemperature:1,gasTemperature:300,absorbedPower:100,alpha:1,plasmaResistance:1,plasmaReactance:1,dcOffset:biasPower ? -10 : null,peakToPeak:biasPower ? 20 : null,currentDensityPeak:1,electronDensity:1e10,ionDensity:1e10,metastableDensity:1e8,neutralDensity:1e12,ionFluxRaw:2e18,metastableFluxRaw:1e18,neutralFluxRaw:1e18,
 residualTrace:[[0,1e-5],[2,2e-8]],iad:biasPower ? [[0,1],[10,2]]:null,iead:biasPower ? {energies:[1,2],angles:[0,10],values:[1,2,3,4],sourceShape:[2,2],angleRange:[0,10]}:null,
 current:biasPower ? {points:[[0,1],[1,2]],phaseRange:[0,1],sourceCount:2}:null,potential:biasPower ? {points:[[0,-10],[1,10]],phaseRange:[0,1],sourceCount:2}:null,density:biasPower ? {rows:[[0,[0,0.1],[1,2]],[1,[0,0.2],[2,3]]],sourceShape:[2,2]}:null},
 iedDistribution:biasPower ? [{energy:1,intensity:2},{energy:2,intensity:3}]:[],sourceFiles:[{name:'synthetic.dat',path:'P6/synthetic.dat',type:'DAT',size:'1 KB',status:'READY'}]};
}
export const fixtureRuns=[syntheticRun(),syntheticRun(0),syntheticRun(600,4),syntheticRun(600,6,200)];

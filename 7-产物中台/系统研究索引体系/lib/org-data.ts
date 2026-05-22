import fs from 'fs';
import path from 'path';
import type { OrgTreeData } from './org-types';
import { applyStatusInference } from './status-inference';

const DATA_DIR = path.join(process.cwd(), 'data');

/** Get raw org tree data */
export function getOrgTreeData(): OrgTreeData {
  const filePath = path.join(DATA_DIR, 'org_tree.json');
  const raw = fs.readFileSync(filePath, 'utf-8');
  return JSON.parse(raw) as OrgTreeData;
}

/** Get org tree with inferred node status */
export function getOrgTreeWithStatus(): OrgTreeData {
  const orgData = getOrgTreeData();

  // Load artifacts for status inference
  const artifactsPath = path.join(DATA_DIR, 'artifacts_index.json');
  const rawIndex = fs.readFileSync(artifactsPath, 'utf-8');
  const artifacts = JSON.parse(rawIndex) as {
    chain_phase: string;
    status: string;
    date: string;
  }[];

  return applyStatusInference(orgData, artifacts);
}

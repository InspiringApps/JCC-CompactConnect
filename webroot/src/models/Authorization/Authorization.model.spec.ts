//
//  Authorization.model.spec.ts
//  CompactConnect
//
//  Created by InspiringApps on 10/29/2026.
//

import { expect } from 'chai';
import { Authorization } from '@models/Authorization/Authorization.model';

describe('Authorization model', () => {
    it('should create a Authorization', () => {
        const authorization = new Authorization();

        expect(authorization).to.be.an.instanceof(Authorization);
    });
});

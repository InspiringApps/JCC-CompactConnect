//
//  styleguide.js
//  InspiringApps modules
//
//  Created by InspiringApps on 5/19/20.
//  Copyright © 2024. InspiringApps. All rights reserved.
//
import { axeConfig } from '../support/axe-config';

// https://docs.cypress.io/api/introduction/api.html
describe('Styleguide page', () => {
    before(() => {
        cy.visit('/styleguide');
    });

    it('should pass accessibility tests', () => {
        cy.injectAxe();
        cy.configureAxe(axeConfig);
        cy.checkA11y('.style-guide-content');
    });
});

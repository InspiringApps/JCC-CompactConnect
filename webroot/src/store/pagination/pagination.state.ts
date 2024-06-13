//
//  pagination.state.ts
//  InspiringApps modules
//
//  Created by InspiringApps on 5/22/20.
//  Copyright © 2024. InspiringApps. All rights reserved.
//

export const DEFAULT_PAGE = 1;
export const DEFAULT_PAGE_SIZE = 5;

export interface State {
    paginationMap: {
        page?: number;
        size?: number;
    };
}

export const paginationTemplate = {
    page: DEFAULT_PAGE,
    size: DEFAULT_PAGE_SIZE,
};

export const state: State = {
    paginationMap: {}
};

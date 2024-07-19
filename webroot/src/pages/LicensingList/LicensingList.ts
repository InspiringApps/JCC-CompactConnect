//
//  LicensingList.ts
//  CompactConnect
//
//  Created by InspiringApps on 7/1/2024.
//

import { Component, Vue } from 'vue-facing-decorator';
import Section from '@components/Section/Section.vue';
import LicenseeList from '@components/Licensee/LicenseeList/LicenseeList.vue';

@Component({
    name: 'LicensingList',
    components: {
        Section,
        LicenseeList,
    },
})
export default class LicensingList extends Vue {
}

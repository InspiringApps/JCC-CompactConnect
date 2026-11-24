//
//  ApplicationQuestionRow.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/24/2026.
//

import {
    Component,
    mixins,
    Prop,
    toNative
} from 'vue-facing-decorator';
import MixinInput from '@components/Forms/_mixins/input.mixin';
import InputRadioGroup from '@components/Forms/InputRadioGroup/InputRadioGroup.vue';

@Component({
    name: 'ApplicationQuestionRow',
    components: {
        InputRadioGroup,
    },
})
class ApplicationQuestionRow extends mixins(MixinInput) {
    @Prop({ default: false }) isStacked?: boolean;
}

export default toNative(ApplicationQuestionRow);

// export default ApplicationQuestionRow;
